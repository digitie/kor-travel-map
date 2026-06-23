"""Dagster resource factory.

운영 배포는 이 module의 기본 resource를 그대로 쓰거나, 테스트/특수 배포에서
``Definitions(..., resources={...})``로 교체한다.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, cast

import httpx
from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.geocoding import KorTravelGeoRestClient, kor_travel_geo_reverse_geocoder
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.file_store import (
    S3ObjectStore,
    build_s3_object_store,
    create_s3_client,
)
from kortravelmap.settings import KorTravelMapSettings

from dagster import InitResourceContext, ResourceDefinition, resource

from .provider_fetchers import (
    fetch_airkorea_air_quality,
    fetch_airkorea_stations,
    fetch_datagokr_cultural_festivals,
    fetch_khoa_beaches,
    fetch_kma_weather_alerts,
    fetch_knps_geometry_records,
    fetch_knps_point_records,
    fetch_kor_travel_concierge_youtube_features,
    fetch_krairport_airports,
    fetch_krex_rest_area_weather,
    fetch_krex_rest_areas,
    fetch_krex_traffic_notices,
    fetch_krforest_arboretums,
    fetch_krforest_recreation_forests,
    fetch_krheritage_events,
    fetch_krheritage_items,
    fetch_mcst_culture_records,
    fetch_mois_license_records,
    fetch_opinet_stations,
    fetch_standard_museums,
    fetch_standard_parking_lots,
    fetch_standard_tourist_attractions,
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
    "kma_datagokr_client_resource",
    "kma_weather_client_resource",
    "kor_travel_map_client_resource",
    "offline_upload_store_resource",
    "reverse_geocoder_resource",
]


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
        resource_key="opinet_stations",
        provider_package="python-opinet-api",
        dataset_key="opinet_fuel_station_details",
        setting_names=("opinet_api_key",),
        source_env_names=("OPINET_API_KEY",),
        note="OpiNet은 전체 station dump endpoint가 없어 지역/좌표 scope 정책이 필요하다.",
    ),
    ProviderRecordResourceSpec(
        resource_key="krex_rest_areas",
        provider_package="python-krex-api",
        dataset_key="krex_rest_areas",
        setting_names=("krex_go_api_key", "data_go_kr_service_key"),
        source_env_names=("KEX_GO_API_KEY", "DATA_GO_KR_SERVICE_KEY"),
    ),
    ProviderRecordResourceSpec(
        resource_key="krex_rest_area_weather",
        provider_package="python-krex-api",
        dataset_key="krex_rest_area_weather",
        setting_names=("krex_ex_api_key",),
        source_env_names=("KEX_GO_API_KEY",),
        note="restWeatherList(EX)는 전국 휴게소 관측 기상을 1시간 snapshot으로 반환.",
    ),
    ProviderRecordResourceSpec(
        resource_key="krex_traffic_notices",
        provider_package="python-krex-api",
        dataset_key="krex_traffic_notices",
        setting_names=("krex_ex_api_key",),
        source_env_names=("KEX_GO_API_KEY",),
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
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
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
        resource_key="khoa_beaches",
        provider_package="python-khoa-api",
        dataset_key="khoa_beaches",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
        note="khoa 해수욕장정보는 시도별 페이지네이션으로 전국을 순회한다.",
    ),
    ProviderRecordResourceSpec(
        resource_key="krairport_airports",
        provider_package="python-krairport-api",
        dataset_key="krairport_airports",
        note="공항 메타데이터는 번들 정적 데이터(keyless).",
    ),
    ProviderRecordResourceSpec(
        resource_key="airkorea_stations",
        provider_package="python-airkorea-api",
        dataset_key="airkorea_stations",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
        note="대기질 측정소(weather-kind feature) — 측정값과 station_name으로 조인.",
    ),
    ProviderRecordResourceSpec(
        resource_key="airkorea_air_quality",
        provider_package="python-airkorea-api",
        dataset_key="airkorea_air_quality",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
        note="대기질 실시간 측정값 → 오염물질별 WeatherValue(시도별 전국 순회).",
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
        source_env_names=("API_KEYS",),
        note=(
            "kor-travel-concierge의 /api/v1/features/{snapshot|changes} REST export를 "
            "pull한다. source env API_KEYS 중 하나를 kor-travel-map API key로 주입한다."
        ),
    ),
    ProviderRecordResourceSpec(
        resource_key="kma_weather_alert_records",
        provider_package="python-kma-api",
        dataset_key="kma_weather_alerts",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
        note=(
            "기상특보 getWthrWrnList — 전국 발표관서(108) rolling window 조회. "
            "특보 종류/등급 구조화는 kma_weather.weather_warning_rows adapter."
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
        description=(
            f"{spec.resource_key} provider record guard "
            f"({spec.provider_package}, {spec.dataset_key})."
        )
    )
    def _resource(_context: InitResourceContext) -> object:
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
        description=(
            f"{spec.resource_key} provider record live fetcher "
            f"({spec.provider_package}, {spec.dataset_key})."
        )
    )
    def _resource(_context: InitResourceContext) -> Iterable[Any] | AsyncIterator[Any]:
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

_OPINET_STATIONS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "opinet_stations"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["opinet_stations"] = (
    build_provider_record_live_resource(
        _OPINET_STATIONS_SPEC,
        fetch_opinet_stations,
    )
)

_KREX_REST_AREAS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "krex_rest_areas"
)
"""krex 휴게소 spec 참조 (live resource override용)."""

PROVIDER_RECORD_RESOURCE_DEFINITIONS["krex_rest_areas"] = (
    build_provider_record_live_resource(
        _KREX_REST_AREAS_SPEC,
        fetch_krex_rest_areas,
    )
)

_KREX_REST_AREA_WEATHER_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "krex_rest_area_weather"
)
"""krex 휴게소 관측 기상 spec 참조 (live resource override용)."""

PROVIDER_RECORD_RESOURCE_DEFINITIONS["krex_rest_area_weather"] = (
    build_provider_record_live_resource(
        _KREX_REST_AREA_WEATHER_SPEC,
        fetch_krex_rest_area_weather,
    )
)

_KREX_TRAFFIC_NOTICES_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "krex_traffic_notices"
)
"""krex 교통 공지 spec 참조 (live resource override용)."""

PROVIDER_RECORD_RESOURCE_DEFINITIONS["krex_traffic_notices"] = (
    build_provider_record_live_resource(
        _KREX_TRAFFIC_NOTICES_SPEC,
        fetch_krex_traffic_notices,
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
"""MOIS 인허가 spec 참조 (live resource override용).

NOTE: spec의 ``setting_names``는 Phase A download용 ``data_go_kr_service_key``를
가리키며, live builder의 guard 활성 판정도 이 값을 본다. Phase B fetcher가 실제로
필요로 하는 것은 ``mois_source_db_path``(소스 DB 경로)이며, fetcher 내부에서 이를
검증해 부재 시 ``ProviderCredentialMissing``으로 실패한다. ``setting_names``는 guard
메시지/env 매핑 보존을 위해 그대로 둔다(변경하지 않음).
"""

PROVIDER_RECORD_RESOURCE_DEFINITIONS["mois_license_records"] = (
    build_provider_record_live_resource(
        _MOIS_LICENSE_RECORDS_SPEC,
        fetch_mois_license_records,
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
    build_provider_record_live_resource(
        _KNPS_POINT_RECORDS_SPEC,
        fetch_knps_point_records,
    )
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["knps_geometry_records"] = (
    build_provider_record_live_resource(
        _KNPS_GEOMETRY_RECORDS_SPEC,
        fetch_knps_geometry_records,
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

_KRAIRPORT_AIRPORTS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "krairport_airports"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["krairport_airports"] = (
    build_provider_record_live_resource(
        _KRAIRPORT_AIRPORTS_SPEC,
        fetch_krairport_airports,
    )
)

_AIRKOREA_STATIONS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "airkorea_stations"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["airkorea_stations"] = (
    build_provider_record_live_resource(
        _AIRKOREA_STATIONS_SPEC,
        fetch_airkorea_stations,
    )
)

_AIRKOREA_AIR_QUALITY_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "airkorea_air_quality"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["airkorea_air_quality"] = (
    build_provider_record_live_resource(
        _AIRKOREA_AIR_QUALITY_SPEC,
        fetch_airkorea_air_quality,
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

_KMA_WEATHER_ALERT_RECORDS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "kma_weather_alert_records"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["kma_weather_alert_records"] = (
    build_provider_record_live_resource(
        _KMA_WEATHER_ALERT_RECORDS_SPEC,
        fetch_kma_weather_alerts,
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


@resource(
    description=(
        "kma_weather_client provider live client (python-kma-api, "
        "kma_ultra_short_nowcast/kma_ultra_short_forecast/kma_short_forecast)."
    )
)
def kma_weather_client_resource(_context: InitResourceContext) -> Iterator[Any]:
    """``python-kma-api`` ``KmaClient`` live 인스턴스 (T-219b).

    KMA weather asset은 대상 격자가 DB(``ops.poi_cache_targets``)에서 나와
    record-stream resource 패턴이 맞지 않는다 — client 자체를 resource로
    노출하고 asset이 격자별로 직접 호출한다(ADR-006 wrapper 없음, 계획 정본
    §2.3). credential이 없으면 guard와 동일한 helpful message로 실패한다.
    """
    settings = KorTravelMapSettings()
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise RuntimeError(
            "Dagster resource 'kma_weather_client'는 기본 실행 비활성 상태: "
            "credential 환경변수가 설정되지 않았음. provider=python-kma-api, "
            "dataset=kma_ultra_short_nowcast/kma_ultra_short_forecast/"
            "kma_short_forecast. kor-travel-map env: KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY; "
            "source env: DATA_GO_KR_SERVICE_KEY."
        )
    # provider public client는 ADR-044 로컬 체크아웃이며 hard dependency가
    # 아니므로(부재 가능) 호출 시점에 lazy import한다.
    kma = cast(Any, importlib.import_module("kma"))
    client = kma.KmaClient(service_key=secret.get_secret_value())
    try:
        yield client
    finally:
        client.close()


@resource(
    description=(
        "kma_datagokr_client provider live client (python-kma-api DataGoKrClient, "
        "kma_mid_forecast)."
    )
)
def kma_datagokr_client_resource(_context: InitResourceContext) -> Iterator[Any]:
    """``python-kma-api`` ``DataGoKrClient`` live 인스턴스 (T-219c).

    중기예보(``getMidLandFcst``/``getMidTa``)는 대상 region이 설정
    (``kma_mid_region_features``)에서 나와 record-stream resource 패턴이 맞지
    않는다 — client 자체를 resource로 노출하고 mid asset이 region별로 직접
    호출한다(ADR-006 wrapper 없음). credential이 없으면 guard와 동일한
    helpful message로 실패한다.
    """
    settings = KorTravelMapSettings()
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise RuntimeError(
            "Dagster resource 'kma_datagokr_client'는 기본 실행 비활성 상태: "
            "credential 환경변수가 설정되지 않았음. provider=python-kma-api, "
            "dataset=kma_mid_forecast. "
            "kor-travel-map env: KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY; "
            "source env: DATA_GO_KR_SERVICE_KEY."
        )
    kma = cast(Any, importlib.import_module("kma"))
    client = kma.DataGoKrClient(service_key=secret.get_secret_value())
    try:
        yield client
    finally:
        client.close()


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
        base_url=settings.kor_travel_geo_base_url,
        timeout=settings.kor_travel_geo_timeout_seconds,
    )
    try:
        yield kor_travel_geo_reverse_geocoder(
            KorTravelGeoRestClient(http),
            region_fallback_radius_km=0.1,
        )
    finally:
        _run_async_resource_teardown(http.aclose())


@resource(description="kor-travel-map app DB에 연결된 AsyncKorTravelMapClient.")
def kor_travel_map_client_resource(
    _context: InitResourceContext,
) -> Iterator[AsyncKorTravelMapClient]:
    """Dagster ``kor_travel_map_client`` 기본 resource."""
    settings = KorTravelMapSettings()
    engine = make_async_engine(settings.pg_dsn)
    try:
        yield AsyncKorTravelMapClient(engine, settings=settings)
    finally:
        _dispose_async_engine(engine)
