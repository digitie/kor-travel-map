"""Dagster resource factory.

운영 배포는 이 module의 기본 resource를 그대로 쓰거나, 테스트/특수 배포에서
``Definitions(..., resources={...})``로 교체한다.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, cast

from dagster import InitResourceContext, ResourceDefinition, resource
from krtour.map.client import AsyncKrtourMapClient
from krtour.map.infra.db import make_async_engine
from krtour.map.infra.file_store import (
    S3ObjectStore,
    build_s3_object_store,
    create_s3_client,
)
from krtour.map.settings import KrtourMapSettings

from .provider_fetchers import (
    fetch_datagokr_cultural_festivals,
    fetch_knps_geometry_records,
    fetch_knps_point_records,
    fetch_krex_rest_areas,
    fetch_krex_traffic_notices,
    fetch_krforest_arboretums,
    fetch_krforest_recreation_forests,
    fetch_krheritage_events,
    fetch_mois_license_records,
    fetch_standard_museums,
)

__all__ = [
    "PROVIDER_RECORD_RESOURCE_DEFINITIONS",
    "PROVIDER_RECORD_RESOURCE_SPECS",
    "ProviderRecordResourceSpec",
    "build_offline_upload_store_from_settings",
    "build_provider_record_guard_resource",
    "build_provider_record_live_resource",
    "create_s3_client_from_settings",
    "krtour_map_client_resource",
    "offline_upload_store_resource",
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
    def krtour_map_env_names(self) -> tuple[str, ...]:
        return tuple(f"KRTOUR_MAP_{name.upper()}" for name in self.setting_names)


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
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
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
)
"""Feature load asset provider record resource별 env/package 매핑."""


def _provider_guard_message(
    spec: ProviderRecordResourceSpec,
    *,
    has_required_settings: bool,
) -> str:
    krtour_env = ", ".join(spec.krtour_map_env_names) or "auth env 없음"
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
        f"krtour-map env: {krtour_env}; source env: {source_env}. "
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
        settings = KrtourMapSettings()
        has_required_settings = all(
            getattr(settings, setting_name) is not None for setting_name in spec.setting_names
        )
        raise RuntimeError(
            _provider_guard_message(spec, has_required_settings=has_required_settings)
        )

    return _resource


def build_provider_record_live_resource(
    spec: ProviderRecordResourceSpec,
    fetch: Callable[[KrtourMapSettings], Iterable[Any] | AsyncIterator[Any]],
) -> ResourceDefinition:
    """provider public client live fetcher를 resource value로 노출한다.

    credential이 없으면 guard와 동일한 helpful message로 ``RuntimeError``를
    던져 missing-credential 동작을 graceful하게 유지한다. credential이 있으면
    ``fetch(settings)``가 반환한 record iterable(sync ``Iterable`` 또는 async
    generator)을 그대로 돌려준다(여기서 소비하지 않음 — asset의
    ``_record_batches``가 sync/async 모두 lazy하게 iterate).
    """

    @resource(
        description=(
            f"{spec.resource_key} provider record live fetcher "
            f"({spec.provider_package}, {spec.dataset_key})."
        )
    )
    def _resource(_context: InitResourceContext) -> Iterable[Any] | AsyncIterator[Any]:
        settings = KrtourMapSettings()
        has_required_settings = all(
            getattr(settings, setting_name) is not None for setting_name in spec.setting_names
        )
        if not has_required_settings:
            raise RuntimeError(
                _provider_guard_message(spec, has_required_settings=False)
            )
        return fetch(settings)

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


def build_offline_upload_store_from_settings(
    settings: KrtourMapSettings,
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


def create_s3_client_from_settings(settings: KrtourMapSettings) -> Any:
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
        name="krtour-map-dagster-resource-teardown",
    )
    thread.start()
    thread.join()
    if raised:
        raise raised[0]


def _dispose_async_engine(engine: Any) -> None:
    dispose_result = engine.dispose()
    if inspect.isawaitable(dispose_result):
        _run_async_resource_teardown(cast("Awaitable[object]", dispose_result))


@resource(description="admin offline upload 원본 파일을 읽는 RustFS/S3 store.")
def offline_upload_store_resource(_context: InitResourceContext) -> S3ObjectStore:
    """Dagster ``offline_upload_store`` 기본 resource."""
    return build_offline_upload_store_from_settings(KrtourMapSettings())


@resource(description="krtour-map app DB에 연결된 AsyncKrtourMapClient.")
def krtour_map_client_resource(
    _context: InitResourceContext,
) -> Iterator[AsyncKrtourMapClient]:
    """Dagster ``krtour_map_client`` 기본 resource."""
    settings = KrtourMapSettings()
    engine = make_async_engine(settings.pg_dsn)
    try:
        yield AsyncKrtourMapClient(engine, settings=settings)
    finally:
        _dispose_async_engine(engine)
