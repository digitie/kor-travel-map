"""Dagster Feature 적재 operation의 공용 불변 identity registry.

Dagster run tag는 이 모듈이 만든 canonical identity의 운반 수단일 뿐 정본이 아니다.
등록 job은 job/asset selection, run config snapshot, registry version을 다시 계산해 모두
일치할 때만 실행할 수 있다. 등록되지 않은 user-code job은 ``None``을 반환해 canonical
DB tracking이 아닌 Dagster 보조 패널에만 남긴다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, cast

from pydantic_settings import BaseSettings, SettingsConfigDict

from kortravelmap.core.feature_operation import (
    TRIGGER_KIND_VALUES,
    ProviderDatasetOperationKey,
    TriggerKind,
)
from kortravelmap.providers.airkorea import (
    AIRKOREA_PROVIDER_NAME,
    DATASET_KEY_AIR_QUALITY,
)
from kortravelmap.providers.datagokr_file_data import (
    DATAGOKR_FILEDATA_DATASETS,
    DATAGOKR_FILEDATA_PROVIDER_NAME,
)
from kortravelmap.providers.khoa import DATASET_KEY_BEACHES, KHOA_PROVIDER_NAME
from kortravelmap.providers.kma import (
    KMA_MID_FORECAST_DATASET_KEY,
    KMA_PROVIDER_NAME,
    KMA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
    KMA_WEATHER_ALERT_DATASET_KEY,
)
from kortravelmap.providers.knps import (
    KNPS_GEOMETRY_DATASETS,
    KNPS_PLACE_DATASETS,
)
from kortravelmap.providers.knps import (
    PROVIDER_NAME as KNPS_PROVIDER_NAME,
)
from kortravelmap.providers.kor_travel_concierge import (
    DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
    KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
)
from kortravelmap.providers.krairport import (
    DATASET_KEY_AIRPORTS,
    KRAIRPORT_PROVIDER_NAME,
)
from kortravelmap.providers.krex import (
    KREX_PROVIDER_NAME,
    REST_AREA_DATASET_KEY,
    REST_AREA_PRICES_DATASET_KEY,
    REST_AREA_WEATHER_DATASET_KEY,
    TRAFFIC_NOTICES_DATASET_KEY,
)
from kortravelmap.providers.krforest import (
    DATASET_KEY_ARBORETUMS,
    DATASET_KEY_RECREATION_FORESTS,
    KRFOREST_PROVIDER_NAME,
)
from kortravelmap.providers.krheritage import (
    DATASET_KEY_EVENT as KRHERITAGE_DATASET_KEY_EVENT,
)
from kortravelmap.providers.krheritage import (
    DATASET_KEY_HERITAGE,
)
from kortravelmap.providers.krheritage import (
    PROVIDER_NAME as KRHERITAGE_PROVIDER_NAME,
)
from kortravelmap.providers.mcst import MCST_FILE_DATASETS, MCST_PROVIDER_NAME
from kortravelmap.providers.mois import (
    DATASET_KEY_BULK,
)
from kortravelmap.providers.mois import (
    PROVIDER_NAME as MOIS_PROVIDER_NAME,
)
from kortravelmap.providers.opinet import (
    OPINET_PRICE_DATASET_KEY,
    OPINET_PROVIDER_NAME,
    OPINET_STATION_DATASET_KEY,
)
from kortravelmap.providers.standard_data import (
    DATASET_KEY_CULTURAL_FESTIVALS,
    DATASET_KEY_MUSEUMS,
    DATASET_KEY_PARKING_LOTS,
    DATASET_KEY_SPECIAL_STREETS,
    DATASET_KEY_TOURIST_ATTRACTIONS,
    STANDARD_DATA_PROVIDER_NAME,
)
from kortravelmap.providers.visitkorea import (
    DATASET_KEY_FESTIVAL_EVENTS,
    VISITKOREA_PROVIDER_NAME,
)

FEATURE_OPERATION_REGISTRY_SCHEMA_VERSION: Final[str] = "v1"

FEATURE_OPERATION_IDENTITY_TAG: Final[str] = "kor_travel_map.operation_identity"
FEATURE_OPERATION_REGISTRY_VERSION_TAG: Final[str] = (
    "kor_travel_map.operation_registry_version"
)
FEATURE_OPERATION_TRIGGER_TAG: Final[str] = "kor_travel_map.trigger_kind"
FEATURE_OPERATION_PROVIDER_TAG: Final[str] = "kor_travel_map.provider"
FEATURE_OPERATION_DATASET_TAG: Final[str] = "kor_travel_map.dataset_key"

FEATURE_UPDATE_REQUEST_ID_TAG: Final[str] = "kor_travel_map.feature_update_request_id"
ADMIN_MANUAL_TRIGGER_TAG: Final[str] = "kor_travel_map.admin_manual"
INTERNAL_SYSTEM_TRIGGER_TAG: Final[str] = "kor_travel_map.internal_system"
DAGSTER_SCHEDULE_NAME_TAG: Final[str] = "dagster/schedule_name"
DAGSTER_SENSOR_NAME_TAG: Final[str] = "dagster/sensor_name"
DAGSTER_BACKFILL_ID_TAG: Final[str] = "dagster/backfill"

SnapshotKind = Literal["static", "datagokr_file_data", "knps_point", "knps_geometry"]

_DEFAULT_KNPS_POINT_DATASET_KEY: Final[str] = "knps_visitor_centers"
_DEFAULT_KNPS_GEOMETRY_DATASET_KEY: Final[str] = "knps_trails"


class _FeatureOperationRuntimeSettings(BaseSettings):
    """operation compile에 필요한 두 필드만 읽는 좁은 settings."""

    model_config = SettingsConfigDict(
        env_prefix="KOR_TRAVEL_MAP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    knps_point_dataset_key: str = _DEFAULT_KNPS_POINT_DATASET_KEY
    knps_geometry_dataset_key: str = _DEFAULT_KNPS_GEOMETRY_DATASET_KEY


class FeatureOperationRegistryError(RuntimeError):
    """등록 operation identity의 누락 또는 drift."""

    code = "FEATURE_OPERATION_REGISTRY_CONFLICT"

    def __init__(self, reason: str, *, job_name: str) -> None:
        message = f"Feature operation registry conflict: {reason}; job={job_name!r}"
        super().__init__(message)
        self.reason = reason
        self.job_name = job_name


@dataclass(frozen=True, slots=True)
class FeatureOperationRegistryEntry:
    """job/asset selection에 대응하는 immutable operation 정의."""

    job_name: str
    asset_keys: tuple[str, ...]
    pairs: tuple[ProviderDatasetOperationKey, ...]
    snapshot_kind: SnapshotKind = "static"
    allowed_dataset_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FeatureOperationRuntimeSnapshot:
    """launch 시점에 고정하는 비민감 설정값."""

    knps_point_dataset_key: str
    knps_geometry_dataset_key: str


@dataclass(frozen=True, slots=True)
class FeatureOperationIdentity:
    """registry에서 해석한 canonical run identity."""

    job_name: str
    asset_keys: tuple[str, ...]
    pairs: tuple[ProviderDatasetOperationKey, ...]
    config_snapshot: tuple[tuple[str, str], ...]
    registry_version: str

    def canonical_json(self) -> str:
        value = {
            "assets": list(self.asset_keys),
            "config_snapshot": dict(self.config_snapshot),
            "job": self.job_name,
            "pairs": [
                {"dataset_key": pair.dataset_key, "provider": pair.provider}
                for pair in self.pairs
            ],
            "registry_version": self.registry_version,
        }
        return json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


def _pair(provider: str, dataset_key: str) -> ProviderDatasetOperationKey:
    return ProviderDatasetOperationKey(provider, dataset_key)


def _static(
    job_name: str,
    asset_key: str,
    provider: str,
    dataset_key: str,
) -> FeatureOperationRegistryEntry:
    return FeatureOperationRegistryEntry(
        job_name=job_name,
        asset_keys=(asset_key,),
        pairs=(_pair(provider, dataset_key),),
    )


_STATIC_ENTRIES: Final[tuple[FeatureOperationRegistryEntry, ...]] = (
    _static(
        "feature_event_datagokr_cultural_festivals_job",
        "feature_event_datagokr_cultural_festivals",
        STANDARD_DATA_PROVIDER_NAME,
        DATASET_KEY_CULTURAL_FESTIVALS,
    ),
    _static(
        "feature_place_opinet_stations_job",
        "feature_place_opinet_stations",
        OPINET_PROVIDER_NAME,
        OPINET_STATION_DATASET_KEY,
    ),
    _static(
        "feature_price_opinet_stations_job",
        "feature_price_opinet_stations",
        OPINET_PROVIDER_NAME,
        OPINET_PRICE_DATASET_KEY,
    ),
    _static(
        "feature_place_krex_rest_areas_job",
        "feature_place_krex_rest_areas",
        KREX_PROVIDER_NAME,
        REST_AREA_DATASET_KEY,
    ),
    _static(
        "feature_price_krex_rest_areas_job",
        "feature_price_krex_rest_areas",
        KREX_PROVIDER_NAME,
        REST_AREA_PRICES_DATASET_KEY,
    ),
    _static(
        "feature_notice_krex_traffic_notices_job",
        "feature_notice_krex_traffic_notices",
        KREX_PROVIDER_NAME,
        TRAFFIC_NOTICES_DATASET_KEY,
    ),
    _static(
        "feature_weather_krex_rest_areas_job",
        "feature_weather_krex_rest_areas",
        KREX_PROVIDER_NAME,
        REST_AREA_WEATHER_DATASET_KEY,
    ),
    _static(
        "feature_place_krheritage_items_job",
        "feature_place_krheritage_items",
        KRHERITAGE_PROVIDER_NAME,
        DATASET_KEY_HERITAGE,
    ),
    _static(
        "feature_event_krheritage_events_job",
        "feature_event_krheritage_events",
        KRHERITAGE_PROVIDER_NAME,
        KRHERITAGE_DATASET_KEY_EVENT,
    ),
    _static(
        "feature_place_mois_licenses_job",
        "feature_place_mois_licenses",
        MOIS_PROVIDER_NAME,
        DATASET_KEY_BULK,
    ),
    _static(
        "feature_place_krforest_recreation_forests_job",
        "feature_place_krforest_recreation_forests",
        KRFOREST_PROVIDER_NAME,
        DATASET_KEY_RECREATION_FORESTS,
    ),
    _static(
        "feature_place_krforest_arboretums_job",
        "feature_place_krforest_arboretums",
        KRFOREST_PROVIDER_NAME,
        DATASET_KEY_ARBORETUMS,
    ),
    _static(
        "feature_place_standard_museums_job",
        "feature_place_standard_museums",
        STANDARD_DATA_PROVIDER_NAME,
        DATASET_KEY_MUSEUMS,
    ),
    _static(
        "feature_place_standard_tourist_attractions_job",
        "feature_place_standard_tourist_attractions",
        STANDARD_DATA_PROVIDER_NAME,
        DATASET_KEY_TOURIST_ATTRACTIONS,
    ),
    _static(
        "feature_place_standard_parking_lots_job",
        "feature_place_standard_parking_lots",
        STANDARD_DATA_PROVIDER_NAME,
        DATASET_KEY_PARKING_LOTS,
    ),
    _static(
        "feature_place_standard_special_streets_job",
        "feature_place_standard_special_streets",
        STANDARD_DATA_PROVIDER_NAME,
        DATASET_KEY_SPECIAL_STREETS,
    ),
    _static(
        "feature_place_khoa_beaches_job",
        "feature_place_khoa_beaches",
        KHOA_PROVIDER_NAME,
        DATASET_KEY_BEACHES,
    ),
    _static(
        "feature_place_krairport_airports_job",
        "feature_place_krairport_airports",
        KRAIRPORT_PROVIDER_NAME,
        DATASET_KEY_AIRPORTS,
    ),
    _static(
        "feature_place_kor_travel_concierge_youtube_job",
        "feature_place_kor_travel_concierge_youtube",
        KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
        DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
    ),
    _static(
        "feature_event_visitkorea_enrichment_job",
        "feature_event_visitkorea_enrichment",
        VISITKOREA_PROVIDER_NAME,
        DATASET_KEY_FESTIVAL_EVENTS,
    ),
    _static(
        "feature_weather_airkorea_air_quality_job",
        "feature_weather_airkorea_air_quality",
        AIRKOREA_PROVIDER_NAME,
        DATASET_KEY_AIR_QUALITY,
    ),
    _static(
        "feature_weather_kma_ultra_short_nowcast_job",
        "feature_weather_kma_ultra_short_nowcast",
        KMA_PROVIDER_NAME,
        KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
    ),
    _static(
        "feature_weather_kma_ultra_short_forecast_job",
        "feature_weather_kma_ultra_short_forecast",
        KMA_PROVIDER_NAME,
        KMA_ULTRA_SHORT_FORECAST_DATASET_KEY,
    ),
    _static(
        "feature_weather_kma_short_forecast_job",
        "feature_weather_kma_short_forecast",
        KMA_PROVIDER_NAME,
        KMA_SHORT_FORECAST_DATASET_KEY,
    ),
    _static(
        "feature_weather_kma_mid_forecast_job",
        "feature_weather_kma_mid_forecast",
        KMA_PROVIDER_NAME,
        KMA_MID_FORECAST_DATASET_KEY,
    ),
    _static(
        "feature_notice_kma_weather_alerts_job",
        "feature_notice_kma_weather_alerts",
        KMA_PROVIDER_NAME,
        KMA_WEATHER_ALERT_DATASET_KEY,
    ),
)

_DATAGOKR_FILEDATA_ENTRIES: Final[tuple[FeatureOperationRegistryEntry, ...]] = tuple(
    FeatureOperationRegistryEntry(
        job_name=f"feature_place_{dataset_key}_job",
        asset_keys=("feature_place_datagokr_file_data",),
        pairs=(_pair(DATAGOKR_FILEDATA_PROVIDER_NAME, dataset_key),),
        snapshot_kind="datagokr_file_data",
    )
    for dataset_key in DATAGOKR_FILEDATA_DATASETS
)

_KNPS_ENTRIES: Final[tuple[FeatureOperationRegistryEntry, ...]] = (
    FeatureOperationRegistryEntry(
        job_name="feature_place_knps_points_job",
        asset_keys=("feature_place_knps_points",),
        pairs=(),
        snapshot_kind="knps_point",
        allowed_dataset_keys=tuple(sorted(KNPS_PLACE_DATASETS)),
    ),
    FeatureOperationRegistryEntry(
        job_name="feature_geometry_knps_records_job",
        asset_keys=("feature_geometry_knps_records",),
        pairs=(),
        snapshot_kind="knps_geometry",
        allowed_dataset_keys=tuple(sorted(KNPS_GEOMETRY_DATASETS)),
    ),
)

_MCST_ENTRY: Final[FeatureOperationRegistryEntry] = FeatureOperationRegistryEntry(
    job_name="feature_place_mcst_culture_job",
    asset_keys=("feature_place_mcst_culture",),
    pairs=tuple(
        sorted(
            _pair(MCST_PROVIDER_NAME, spec.dataset_key)
            for spec in MCST_FILE_DATASETS.values()
        )
    ),
)

FEATURE_OPERATION_REGISTRY: Final[tuple[FeatureOperationRegistryEntry, ...]] = (
    *_STATIC_ENTRIES,
    *_DATAGOKR_FILEDATA_ENTRIES,
    *_KNPS_ENTRIES,
    _MCST_ENTRY,
)
"""33개 feature-load job의 immutable registry."""

FEATURE_OPERATION_REGISTRY_BY_JOB: Final[
    Mapping[str, FeatureOperationRegistryEntry]
] = MappingProxyType({entry.job_name: entry for entry in FEATURE_OPERATION_REGISTRY})


def _entry_possible_pairs(
    entry: FeatureOperationRegistryEntry,
) -> tuple[ProviderDatasetOperationKey, ...]:
    if entry.snapshot_kind in {"knps_point", "knps_geometry"}:
        return tuple(
            _pair(KNPS_PROVIDER_NAME, key) for key in entry.allowed_dataset_keys
        )
    return entry.pairs


if len(FEATURE_OPERATION_REGISTRY_BY_JOB) != len(FEATURE_OPERATION_REGISTRY):
    raise RuntimeError("Feature operation registry job_name이 중복됨")

_JOB_BY_PAIR: dict[ProviderDatasetOperationKey, str] = {}
for _entry in FEATURE_OPERATION_REGISTRY:
    _possible_pairs = _entry_possible_pairs(_entry)
    if len(_possible_pairs) != len(set(_possible_pairs)):
        raise RuntimeError(
            "Feature operation registry 동일 job 내부 pair가 중복됨: "
            f"{_entry.job_name}"
        )
    for _possible_pair in _possible_pairs:
        _previous_job = _JOB_BY_PAIR.setdefault(_possible_pair, _entry.job_name)
        if _previous_job != _entry.job_name:
            raise RuntimeError(
                "Feature operation registry pair가 여러 job에 중복됨: "
                f"{_possible_pair.provider}/{_possible_pair.dataset_key}"
            )

FEATURE_OPERATION_JOB_BY_PAIR: Final[Mapping[ProviderDatasetOperationKey, str]] = (
    MappingProxyType(_JOB_BY_PAIR)
)
del _JOB_BY_PAIR, _entry, _possible_pair, _possible_pairs, _previous_job


def feature_operation_registry_manifest_json() -> str:
    """registry version digest의 canonical manifest JSON."""
    manifest = [
        {
            "allowed_dataset_keys": list(entry.allowed_dataset_keys),
            "asset_keys": list(entry.asset_keys),
            "job_name": entry.job_name,
            "pairs": [
                {"dataset_key": pair.dataset_key, "provider": pair.provider}
                for pair in entry.pairs
            ],
            "snapshot_kind": entry.snapshot_kind,
        }
        for entry in FEATURE_OPERATION_REGISTRY
    ]
    return json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


FEATURE_OPERATION_REGISTRY_DIGEST: Final[str] = hashlib.sha256(
    feature_operation_registry_manifest_json().encode("utf-8")
).hexdigest()
FEATURE_OPERATION_REGISTRY_VERSION: Final[str] = (
    f"{FEATURE_OPERATION_REGISTRY_SCHEMA_VERSION}-"
    f"{FEATURE_OPERATION_REGISTRY_DIGEST[:12]}"
)


def resolve_feature_operation_runtime_snapshot(
    environment: Mapping[str, str] | None = None,
) -> FeatureOperationRuntimeSnapshot:
    """KNPS 두 필드만 공식 env prefix/``.env`` 의미로 좁게 해석한다."""
    if environment is None:
        settings = _FeatureOperationRuntimeSettings()
        return FeatureOperationRuntimeSnapshot(
            knps_point_dataset_key=settings.knps_point_dataset_key,
            knps_geometry_dataset_key=settings.knps_geometry_dataset_key,
        )
    return FeatureOperationRuntimeSnapshot(
        knps_point_dataset_key=environment.get(
            "KOR_TRAVEL_MAP_KNPS_POINT_DATASET_KEY",
            _DEFAULT_KNPS_POINT_DATASET_KEY,
        ),
        knps_geometry_dataset_key=environment.get(
            "KOR_TRAVEL_MAP_KNPS_GEOMETRY_DATASET_KEY",
            _DEFAULT_KNPS_GEOMETRY_DATASET_KEY,
        ),
    )


def _resource_dataset_key(
    run_config: Mapping[str, object],
    resource_key: str,
) -> str | None:
    resources = run_config.get("resources")
    if not isinstance(resources, Mapping):
        return None
    resource = resources.get(resource_key)
    if not isinstance(resource, Mapping):
        return None
    config = resource.get("config")
    if not isinstance(config, Mapping):
        return None
    value = config.get("dataset_key")
    return value if isinstance(value, str) and value else None


def _resolved_dataset_key(
    entry: FeatureOperationRegistryEntry,
    *,
    run_config: Mapping[str, object] | None,
    runtime_snapshot: FeatureOperationRuntimeSnapshot | None,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    if entry.snapshot_kind == "datagokr_file_data":
        expected = entry.pairs[0].dataset_key
        if run_config is None:
            raise FeatureOperationRegistryError(
                "fileData run config 누락",
                job_name=entry.job_name,
            )
        asset_key = _resource_dataset_key(run_config, "datagokr_file_data_dataset_key")
        records_key = _resource_dataset_key(run_config, "datagokr_file_data_records")
        if asset_key != expected or records_key != expected:
            raise FeatureOperationRegistryError(
                "fileData identity/resource dataset snapshot 불일치",
                job_name=entry.job_name,
            )
        return expected, (("datagokr_file_data_dataset_key", expected),)

    if entry.snapshot_kind == "knps_point":
        resource_names = ("knps_point_dataset_key", "knps_point_records")
        snapshot_name = "knps_point_dataset_key"
        snapshot_value = (
            runtime_snapshot.knps_point_dataset_key
            if runtime_snapshot is not None
            else None
        )
    elif entry.snapshot_kind == "knps_geometry":
        resource_names = ("knps_geometry_dataset_key", "knps_geometry_records")
        snapshot_name = "knps_geometry_dataset_key"
        snapshot_value = (
            runtime_snapshot.knps_geometry_dataset_key
            if runtime_snapshot is not None
            else None
        )
    else:
        raise AssertionError(f"dynamic snapshot kind가 아님: {entry.snapshot_kind}")

    config_values = (
        tuple(_resource_dataset_key(run_config, name) for name in resource_names)
        if run_config is not None
        else ()
    )
    configured_value: str | None = None
    if config_values:
        if None in config_values or len(set(config_values)) != 1:
            raise FeatureOperationRegistryError(
                "KNPS fetcher/asset resource dataset snapshot 불일치",
                job_name=entry.job_name,
            )
        configured_value = cast(str, config_values[0])

    resolved = configured_value or snapshot_value
    if resolved is None:
        raise FeatureOperationRegistryError(
            "KNPS resolved snapshot 누락",
            job_name=entry.job_name,
        )
    if (
        snapshot_value is not None
        and configured_value is not None
        and snapshot_value != configured_value
    ):
        raise FeatureOperationRegistryError(
            "KNPS settings/run config dataset snapshot 불일치",
            job_name=entry.job_name,
        )
    if resolved not in entry.allowed_dataset_keys:
        raise FeatureOperationRegistryError(
            "KNPS dataset이 허용 catalog에 없음",
            job_name=entry.job_name,
        )
    return resolved, ((snapshot_name, resolved),)


def resolve_feature_operation_identity(
    *,
    job_name: str,
    selected_asset_keys: Sequence[str] | None = None,
    run_config: Mapping[str, object] | None = None,
    runtime_snapshot: FeatureOperationRuntimeSnapshot | None = None,
) -> FeatureOperationIdentity | None:
    """등록 job identity를 재계산한다. 비등록 job은 panel-only ``None``이다."""
    entry = FEATURE_OPERATION_REGISTRY_BY_JOB.get(job_name)
    if entry is None:
        return None

    selection = (
        tuple(sorted(entry.asset_keys))
        if selected_asset_keys is None
        else tuple(sorted(selected_asset_keys))
    )
    if selection != tuple(sorted(entry.asset_keys)):
        raise FeatureOperationRegistryError("asset selection drift", job_name=job_name)

    if entry.snapshot_kind == "static":
        pairs = entry.pairs
        config_snapshot: tuple[tuple[str, str], ...] = ()
    else:
        dataset_key, config_snapshot = _resolved_dataset_key(
            entry,
            run_config=run_config,
            runtime_snapshot=runtime_snapshot,
        )
        provider = entry.pairs[0].provider if entry.pairs else KNPS_PROVIDER_NAME
        pairs = (_pair(provider, dataset_key),)

    return FeatureOperationIdentity(
        job_name=entry.job_name,
        asset_keys=tuple(sorted(entry.asset_keys)),
        pairs=tuple(sorted(pairs)),
        config_snapshot=config_snapshot,
        registry_version=FEATURE_OPERATION_REGISTRY_VERSION,
    )


def feature_operation_run_config(
    identity: FeatureOperationIdentity,
) -> dict[str, object]:
    """resolved snapshot과 fetcher/asset resource를 같은 값으로 고정한다."""
    snapshot = dict(identity.config_snapshot)
    if "datagokr_file_data_dataset_key" in snapshot:
        dataset_key = snapshot["datagokr_file_data_dataset_key"]
        resource_names = (
            "datagokr_file_data_dataset_key",
            "datagokr_file_data_records",
        )
    elif "knps_point_dataset_key" in snapshot:
        dataset_key = snapshot["knps_point_dataset_key"]
        resource_names = ("knps_point_dataset_key", "knps_point_records")
    elif "knps_geometry_dataset_key" in snapshot:
        dataset_key = snapshot["knps_geometry_dataset_key"]
        resource_names = ("knps_geometry_dataset_key", "knps_geometry_records")
    else:
        return {}
    return {
        "resources": {
            name: {"config": {"dataset_key": dataset_key}}
            for name in resource_names
        }
    }


def resolve_feature_operation_launch(
    *,
    job_name: str,
    selected_asset_keys: Sequence[str] | None = None,
    runtime_snapshot: FeatureOperationRuntimeSnapshot | None = None,
) -> tuple[FeatureOperationIdentity, dict[str, object]] | None:
    """manifest에서 canonical identity와 실제 launch run config를 함께 만든다."""
    entry = FEATURE_OPERATION_REGISTRY_BY_JOB.get(job_name)
    if entry is None:
        return None

    seed_config: Mapping[str, object] | None = None
    if entry.snapshot_kind == "datagokr_file_data":
        dataset_key = entry.pairs[0].dataset_key
        seed_config = {
            "resources": {
                name: {"config": {"dataset_key": dataset_key}}
                for name in (
                    "datagokr_file_data_dataset_key",
                    "datagokr_file_data_records",
                )
            }
        }
    identity = resolve_feature_operation_identity(
        job_name=job_name,
        selected_asset_keys=selected_asset_keys,
        run_config=seed_config,
        runtime_snapshot=runtime_snapshot,
    )
    if identity is None:
        raise AssertionError(f"등록 job identity 해석 실패: {job_name!r}")
    run_config = feature_operation_run_config(identity)
    recomputed = resolve_feature_operation_identity(
        job_name=job_name,
        selected_asset_keys=identity.asset_keys,
        run_config=run_config,
        runtime_snapshot=runtime_snapshot,
    )
    if recomputed != identity:
        raise FeatureOperationRegistryError(
            "manifest launch config 재계산 불일치",
            job_name=job_name,
        )
    return identity, run_config


def feature_operation_definition_tags(
    identity: FeatureOperationIdentity,
) -> dict[str, str]:
    """trigger를 포함하지 않는 job definition identity tag."""
    tags = {
        FEATURE_OPERATION_IDENTITY_TAG: identity.canonical_json(),
        FEATURE_OPERATION_REGISTRY_VERSION_TAG: identity.registry_version,
    }
    providers = {pair.provider for pair in identity.pairs}
    if len(providers) == 1:
        tags[FEATURE_OPERATION_PROVIDER_TAG] = next(iter(providers))
    if len(identity.pairs) == 1:
        tags[FEATURE_OPERATION_DATASET_TAG] = identity.pairs[0].dataset_key
    return tags


def feature_operation_launch_tags(
    identity: FeatureOperationIdentity,
    *,
    trigger_kind: TriggerKind,
) -> dict[str, str]:
    """schedule/admin/sensor launch가 definition과 분리해 붙이는 tag."""
    if trigger_kind not in TRIGGER_KIND_VALUES:
        raise ValueError(f"알 수 없는 trigger_kind: {trigger_kind!r}")
    return {
        **feature_operation_definition_tags(identity),
        FEATURE_OPERATION_TRIGGER_TAG: trigger_kind,
    }


def parse_feature_operation_identity_tags(
    tags: Mapping[str, str],
) -> FeatureOperationIdentity | None:
    """manifest와 exact 일치하는 canonical identity tag만 strict parse한다."""
    raw_identity = tags.get(FEATURE_OPERATION_IDENTITY_TAG)
    tagged_version = tags.get(FEATURE_OPERATION_REGISTRY_VERSION_TAG)
    if raw_identity is None and tagged_version is None:
        return None
    if raw_identity is None or tagged_version is None:
        raise FeatureOperationRegistryError(
            "identity/version tag가 함께 존재하지 않음",
            job_name="<unknown>",
        )
    try:
        raw = json.loads(raw_identity)
    except (TypeError, ValueError) as exc:
        raise FeatureOperationRegistryError(
            "canonical identity JSON이 아님",
            job_name="<unknown>",
        ) from exc
    if not isinstance(raw, dict) or set(raw) != {
        "assets",
        "config_snapshot",
        "job",
        "pairs",
        "registry_version",
    }:
        raise FeatureOperationRegistryError(
            "canonical identity shape 불일치",
            job_name="<unknown>",
        )
    job_name = raw.get("job")
    if not isinstance(job_name, str) or not job_name:
        raise FeatureOperationRegistryError(
            "canonical identity job 누락",
            job_name="<unknown>",
        )
    entry = FEATURE_OPERATION_REGISTRY_BY_JOB.get(job_name)
    if entry is None:
        raise FeatureOperationRegistryError(
            "manifest에 없는 job identity",
            job_name=job_name,
        )
    if (
        tagged_version != FEATURE_OPERATION_REGISTRY_VERSION
        or raw.get("registry_version") != FEATURE_OPERATION_REGISTRY_VERSION
    ):
        raise FeatureOperationRegistryError(
            "registry version 불일치",
            job_name=job_name,
        )

    raw_assets = raw.get("assets")
    if (
        not isinstance(raw_assets, list)
        or any(not isinstance(value, str) or not value for value in raw_assets)
        or tuple(raw_assets) != tuple(sorted(entry.asset_keys))
    ):
        raise FeatureOperationRegistryError("asset selection drift", job_name=job_name)

    raw_pairs = raw.get("pairs")
    if not isinstance(raw_pairs, list):
        raise FeatureOperationRegistryError("pair 목록 shape 불일치", job_name=job_name)
    pairs: list[ProviderDatasetOperationKey] = []
    for raw_pair in raw_pairs:
        if not isinstance(raw_pair, dict) or set(raw_pair) != {
            "dataset_key",
            "provider",
        }:
            raise FeatureOperationRegistryError(
                "pair shape 불일치",
                job_name=job_name,
            )
        provider = raw_pair.get("provider")
        dataset_key = raw_pair.get("dataset_key")
        if not isinstance(provider, str) or not isinstance(dataset_key, str):
            raise FeatureOperationRegistryError(
                "pair 값 shape 불일치",
                job_name=job_name,
            )
        try:
            pairs.append(_pair(provider, dataset_key))
        except ValueError as exc:
            raise FeatureOperationRegistryError(
                "pair 값이 trimmed non-empty가 아님",
                job_name=job_name,
            ) from exc
    parsed_pairs = tuple(pairs)
    if parsed_pairs != tuple(sorted(parsed_pairs)) or len(set(parsed_pairs)) != len(
        parsed_pairs
    ):
        raise FeatureOperationRegistryError(
            "pair 목록이 canonical sort/unique가 아님",
            job_name=job_name,
        )

    raw_snapshot = raw.get("config_snapshot")
    if not isinstance(raw_snapshot, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in raw_snapshot.items()
    ):
        raise FeatureOperationRegistryError(
            "config snapshot shape 불일치",
            job_name=job_name,
        )
    config_snapshot = tuple(sorted(raw_snapshot.items()))

    if entry.snapshot_kind == "static":
        expected_pairs = entry.pairs
        expected_snapshot: tuple[tuple[str, str], ...] = ()
    elif entry.snapshot_kind == "datagokr_file_data":
        expected_pairs = entry.pairs
        expected_snapshot = (
            ("datagokr_file_data_dataset_key", entry.pairs[0].dataset_key),
        )
    else:
        if len(parsed_pairs) != 1:
            raise FeatureOperationRegistryError(
                "KNPS runtime identity는 exact pair 1개여야 함",
                job_name=job_name,
            )
        pair = parsed_pairs[0]
        snapshot_name = (
            "knps_point_dataset_key"
            if entry.snapshot_kind == "knps_point"
            else "knps_geometry_dataset_key"
        )
        if (
            pair.provider != KNPS_PROVIDER_NAME
            or pair.dataset_key not in entry.allowed_dataset_keys
        ):
            raise FeatureOperationRegistryError(
                "KNPS pair가 허용 manifest에 없음",
                job_name=job_name,
            )
        expected_pairs = (pair,)
        expected_snapshot = ((snapshot_name, pair.dataset_key),)

    if parsed_pairs != expected_pairs or config_snapshot != expected_snapshot:
        raise FeatureOperationRegistryError(
            "manifest pair/config snapshot 불일치",
            job_name=job_name,
        )
    identity = FeatureOperationIdentity(
        job_name=job_name,
        asset_keys=tuple(raw_assets),
        pairs=parsed_pairs,
        config_snapshot=config_snapshot,
        registry_version=FEATURE_OPERATION_REGISTRY_VERSION,
    )
    if identity.canonical_json() != raw_identity:
        raise FeatureOperationRegistryError(
            "identity JSON canonical byte 불일치",
            job_name=job_name,
        )
    expected_tags = feature_operation_definition_tags(identity)
    for tag_name in (FEATURE_OPERATION_PROVIDER_TAG, FEATURE_OPERATION_DATASET_TAG):
        if tags.get(tag_name) != expected_tags.get(tag_name):
            raise FeatureOperationRegistryError(
                "canonical provider/dataset tag 누락/불일치",
                job_name=job_name,
            )
    return identity


def validate_feature_operation_identity(
    *,
    job_name: str,
    selected_asset_keys: Sequence[str],
    run_config: Mapping[str, object] | None,
    tags: Mapping[str, str],
) -> FeatureOperationIdentity | None:
    """run record만으로 identity를 재계산하고 registry 생성 tag와 exact 비교한다."""
    identity = resolve_feature_operation_identity(
        job_name=job_name,
        selected_asset_keys=selected_asset_keys,
        run_config=run_config,
    )
    if identity is None:
        return None
    tagged_identity = parse_feature_operation_identity_tags(tags)
    if tagged_identity != identity:
        raise FeatureOperationRegistryError(
            "run config와 tagged identity 불일치",
            job_name=job_name,
        )
    return identity


def resolve_feature_operation_trigger(
    identity: FeatureOperationIdentity | None,
    tags: Mapping[str, str],
) -> TriggerKind | None:
    """신뢰도 우선순위로 trigger를 판정한다. 비등록 identity는 추측하지 않는다."""
    if identity is None:
        return None

    explicit = tags.get(FEATURE_OPERATION_TRIGGER_TAG)
    if explicit is not None and explicit not in TRIGGER_KIND_VALUES:
        raise FeatureOperationRegistryError(
            "명시 trigger tag가 비었거나 알 수 없음",
            job_name=identity.job_name,
        )
    signals: tuple[tuple[str, TriggerKind], ...] = (
        (FEATURE_UPDATE_REQUEST_ID_TAG, "update_request"),
        (ADMIN_MANUAL_TRIGGER_TAG, "manual"),
        (DAGSTER_SCHEDULE_NAME_TAG, "schedule"),
        (DAGSTER_SENSOR_NAME_TAG, "sensor"),
        (DAGSTER_BACKFILL_ID_TAG, "backfill"),
        (INTERNAL_SYSTEM_TRIGGER_TAG, "system"),
    )
    for tag_name, trigger_kind in signals:
        value = tags.get(tag_name)
        if value is not None:
            if not value.strip():
                raise FeatureOperationRegistryError(
                    "trigger signal tag가 비어 있음",
                    job_name=identity.job_name,
                )
            return trigger_kind
    if explicit is not None:
        return explicit
    return "manual"


def all_feature_operation_registry_pairs() -> tuple[ProviderDatasetOperationKey, ...]:
    """runtime KNPS 선택지를 포함한 registry possible pair 53개."""
    pairs: set[ProviderDatasetOperationKey] = set()
    for entry in FEATURE_OPERATION_REGISTRY:
        pairs.update(_entry_possible_pairs(entry))
    return tuple(sorted(pairs))


__all__ = [
    "ADMIN_MANUAL_TRIGGER_TAG",
    "DAGSTER_BACKFILL_ID_TAG",
    "DAGSTER_SCHEDULE_NAME_TAG",
    "DAGSTER_SENSOR_NAME_TAG",
    "FEATURE_OPERATION_DATASET_TAG",
    "FEATURE_OPERATION_IDENTITY_TAG",
    "FEATURE_OPERATION_JOB_BY_PAIR",
    "FEATURE_OPERATION_PROVIDER_TAG",
    "FEATURE_OPERATION_REGISTRY",
    "FEATURE_OPERATION_REGISTRY_BY_JOB",
    "FEATURE_OPERATION_REGISTRY_DIGEST",
    "FEATURE_OPERATION_REGISTRY_SCHEMA_VERSION",
    "FEATURE_OPERATION_REGISTRY_VERSION",
    "FEATURE_OPERATION_REGISTRY_VERSION_TAG",
    "FEATURE_OPERATION_TRIGGER_TAG",
    "FEATURE_UPDATE_REQUEST_ID_TAG",
    "INTERNAL_SYSTEM_TRIGGER_TAG",
    "FeatureOperationIdentity",
    "FeatureOperationRegistryEntry",
    "FeatureOperationRegistryError",
    "FeatureOperationRuntimeSnapshot",
    "all_feature_operation_registry_pairs",
    "feature_operation_definition_tags",
    "feature_operation_launch_tags",
    "feature_operation_registry_manifest_json",
    "feature_operation_run_config",
    "parse_feature_operation_identity_tags",
    "resolve_feature_operation_identity",
    "resolve_feature_operation_launch",
    "resolve_feature_operation_runtime_snapshot",
    "resolve_feature_operation_trigger",
    "validate_feature_operation_identity",
]
