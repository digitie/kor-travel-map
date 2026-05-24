from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from kraddr.base import Address, PlaceCategoryCode
from sqlalchemy import select

from krtour_map.addressing import (
    AddressMatchReport,
    ReverseGeocoder,
    enrich_address_from_coordinate,
    resolve_reverse_geocoder,
)
from krtour_map.dagster import (
    DagsterEtlExecution,
    DagsterEtlRun,
    EtlJobSpec,
    EtlRunIdentity,
    schedule_is_enabled_by_default,
)
from krtour_map.db import (
    FeatureDbLoadResult,
    feature_place_details,
    features,
    load_feature_rows,
)
from krtour_map.enums import FeatureKind, SourceRole
from krtour_map.ids import make_feature_id, make_payload_hash
from krtour_map.models import Coordinate, Feature, PlaceDetail, RawDataRef

KRMOIS_PROVIDER = "python-krmois-api"
KRMOIS_LICENSE_FEATURE_DATASET_KEY = "krmois_license_features"
KRMOIS_LICENSE_SOURCE_DB_SYNC_KIND = "localdata_full"
KRMOIS_LICENSE_FULL_UPDATE_INTERVAL_DAYS = 7
KRMOIS_LICENSE_DEFAULT_BATCH_SIZE = 1000

KRMOIS_EXCLUDED_SERVICE_SLUGS = frozenset(
    {
        "animal_boarding",
        "animal_hospitals",
        "animal_pharmacies",
        "barber_shops",
        "beauty_salons",
        "billiard_halls",
        "dance_academies",
        "dance_halls",
        "film_screenings",
        "golf_practice_ranges",
        "karaoke_rooms",
        "laundries",
        "lpg_equipment_manufacturers",
        "medical_laundry",
        "oil_retailers",
        "optical_shops",
        "over_the_counter_medicine_stores",
        "pc_bangs",
        "pet_grooming",
        "petroleum_alt_fuel_retailers",
        "video_viewing_rooms",
    }
)


@dataclass(frozen=True)
class KrmoisLicenseFeatureMapping:
    service_slug: str
    category: str
    marker_icon: str
    marker_color: str
    place_kind: str
    feature_group: str
    category_confidence: int


KRMOIS_LICENSE_PROMOTION_MAPPINGS: dict[str, KrmoisLicenseFeatureMapping] = {
    "auto_campgrounds": KrmoisLicenseFeatureMapping(
        "auto_campgrounds",
        PlaceCategoryCode.LODGING_CAMPGROUND_AUTO.value,
        "campsite",
        "#5A8F29",
        "campground",
        "lodging",
        95,
    ),
    "bakeries": KrmoisLicenseFeatureMapping(
        "bakeries",
        PlaceCategoryCode.FOOD_RESTAURANT_BAKERY.value,
        "bakery",
        "#B7791F",
        "food",
        "food",
        90,
    ),
    "city_tour_businesses": KrmoisLicenseFeatureMapping(
        "city_tour_businesses",
        PlaceCategoryCode.TOURISM_ACTIVITY.value,
        "bus",
        "#2B6CB0",
        "activity",
        "tourism_activity",
        75,
    ),
    "comprehensive_amusement_facilities": KrmoisLicenseFeatureMapping(
        "comprehensive_amusement_facilities",
        PlaceCategoryCode.TOURISM_THEME_PARK_AMUSEMENT_LARGE.value,
        "amusement-park",
        "#C05621",
        "theme_park",
        "culture_leisure",
        90,
    ),
    "comprehensive_resorts": KrmoisLicenseFeatureMapping(
        "comprehensive_resorts",
        PlaceCategoryCode.LODGING_RESORT_COMPLEX.value,
        "resort",
        "#6B46C1",
        "resort",
        "lodging",
        90,
    ),
    "entertainment_bars": KrmoisLicenseFeatureMapping(
        "entertainment_bars",
        PlaceCategoryCode.FOOD_RESTAURANT_BAR.value,
        "bar",
        "#9B2C2C",
        "bar",
        "food",
        70,
    ),
    "foreigners_entertainment_restaurants": KrmoisLicenseFeatureMapping(
        "foreigners_entertainment_restaurants",
        PlaceCategoryCode.FOOD_RESTAURANT_BAR.value,
        "bar",
        "#9B2C2C",
        "bar",
        "food",
        70,
    ),
    "foreigner_city_homestays": KrmoisLicenseFeatureMapping(
        "foreigner_city_homestays",
        PlaceCategoryCode.LODGING_GUESTHOUSE_GENERAL.value,
        "lodging",
        "#4A5568",
        "guesthouse",
        "lodging",
        90,
    ),
    "general_amusement_facilities": KrmoisLicenseFeatureMapping(
        "general_amusement_facilities",
        PlaceCategoryCode.TOURISM_THEME_PARK_AMUSEMENT_SMALL.value,
        "amusement-park",
        "#C05621",
        "theme_park",
        "culture_leisure",
        90,
    ),
    "general_campgrounds": KrmoisLicenseFeatureMapping(
        "general_campgrounds",
        PlaceCategoryCode.LODGING_CAMPGROUND.value,
        "campsite",
        "#5A8F29",
        "campground",
        "lodging",
        95,
    ),
    "general_restaurants": KrmoisLicenseFeatureMapping(
        "general_restaurants",
        PlaceCategoryCode.FOOD_RESTAURANT.value,
        "restaurant",
        "#C2410C",
        "restaurant",
        "food",
        80,
    ),
    "golf_courses": KrmoisLicenseFeatureMapping(
        "golf_courses",
        PlaceCategoryCode.TOURISM_ACTIVITY_GOLF.value,
        "golf",
        "#2F855A",
        "activity",
        "sports_leisure",
        95,
    ),
    "hanok_experience": KrmoisLicenseFeatureMapping(
        "hanok_experience",
        PlaceCategoryCode.LODGING_GUESTHOUSE_HANOK.value,
        "lodging",
        "#805AD5",
        "hanok_stay",
        "lodging",
        95,
    ),
    "horse_riding": KrmoisLicenseFeatureMapping(
        "horse_riding",
        PlaceCategoryCode.TOURISM_ACTIVITY_LEISURE_SPORTS.value,
        "horse-riding",
        "#2F855A",
        "activity",
        "sports_leisure",
        75,
    ),
    "hospitals": KrmoisLicenseFeatureMapping(
        "hospitals",
        PlaceCategoryCode.MEDICAL_HOSPITAL_GENERAL.value,
        "hospital",
        "#C53030",
        "medical",
        "medical",
        90,
    ),
    "international_convention_facilities": KrmoisLicenseFeatureMapping(
        "international_convention_facilities",
        PlaceCategoryCode.TOURISM_CULTURAL_FACILITY.value,
        "commercial",
        "#2B6CB0",
        "culture_facility",
        "culture_leisure",
        60,
    ),
    "large_scale_retail_stores": KrmoisLicenseFeatureMapping(
        "large_scale_retail_stores",
        PlaceCategoryCode.CONVENIENCE_DEPARTMENT_STORE.value,
        "shop",
        "#B7791F",
        "retail",
        "retail",
        70,
    ),
    "local_culture_centers": KrmoisLicenseFeatureMapping(
        "local_culture_centers",
        PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_CULTURE_CENTER.value,
        "town-hall",
        "#2B6CB0",
        "culture_facility",
        "culture_leisure",
        90,
    ),
    "lodgings": KrmoisLicenseFeatureMapping(
        "lodgings",
        PlaceCategoryCode.LODGING.value,
        "lodging",
        "#4A5568",
        "lodging",
        "lodging",
        75,
    ),
    "movie_theaters": KrmoisLicenseFeatureMapping(
        "movie_theaters",
        PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_CINEMA.value,
        "cinema",
        "#2B6CB0",
        "culture_facility",
        "culture_leisure",
        95,
    ),
    "museums_and_art_galleries": KrmoisLicenseFeatureMapping(
        "museums_and_art_galleries",
        PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM.value,
        "museum",
        "#2B6CB0",
        "culture_facility",
        "culture_leisure",
        80,
    ),
    "performance_halls": KrmoisLicenseFeatureMapping(
        "performance_halls",
        PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL_GENERAL.value,
        "theatre",
        "#2B6CB0",
        "culture_facility",
        "culture_leisure",
        95,
    ),
    "pharmacies": KrmoisLicenseFeatureMapping(
        "pharmacies",
        PlaceCategoryCode.MEDICAL_PHARMACY_GENERAL.value,
        "pharmacy",
        "#C53030",
        "medical",
        "medical",
        95,
    ),
    "public_baths": KrmoisLicenseFeatureMapping(
        "public_baths",
        PlaceCategoryCode.HOT_SPRING_SPA_SAUNA_BATHHOUSE.value,
        "bath",
        "#3182CE",
        "bathhouse",
        "spa",
        90,
    ),
    "rest_cafes": KrmoisLicenseFeatureMapping(
        "rest_cafes",
        PlaceCategoryCode.FOOD_CAFE.value,
        "cafe",
        "#B7791F",
        "cafe",
        "food",
        75,
    ),
    "singing_bars": KrmoisLicenseFeatureMapping(
        "singing_bars",
        PlaceCategoryCode.FOOD_RESTAURANT_BAR.value,
        "bar",
        "#9B2C2C",
        "bar",
        "food",
        70,
    ),
    "ski_resorts": KrmoisLicenseFeatureMapping(
        "ski_resorts",
        PlaceCategoryCode.TOURISM_ACTIVITY_LEISURE_SPORTS.value,
        "skiing",
        "#2F855A",
        "activity",
        "sports_leisure",
        85,
    ),
    "sledding": KrmoisLicenseFeatureMapping(
        "sledding",
        PlaceCategoryCode.TOURISM_ACTIVITY_LEISURE_SPORTS.value,
        "sledding",
        "#2F855A",
        "activity",
        "sports_leisure",
        75,
    ),
    "special_resorts": KrmoisLicenseFeatureMapping(
        "special_resorts",
        PlaceCategoryCode.LODGING_RESORT.value,
        "resort",
        "#6B46C1",
        "resort",
        "lodging",
        80,
    ),
    "swimming_pools": KrmoisLicenseFeatureMapping(
        "swimming_pools",
        PlaceCategoryCode.TOURISM_ACTIVITY_LEISURE_SPORTS.value,
        "swimming",
        "#2F855A",
        "activity",
        "sports_leisure",
        70,
    ),
    "tourist_accommodations": KrmoisLicenseFeatureMapping(
        "tourist_accommodations",
        PlaceCategoryCode.LODGING_HOTEL_TOURIST.value,
        "lodging",
        "#4A5568",
        "hotel",
        "lodging",
        95,
    ),
    "tourist_cruises": KrmoisLicenseFeatureMapping(
        "tourist_cruises",
        PlaceCategoryCode.TOURISM_ACTIVITY_CRUISE.value,
        "ferry",
        "#2B6CB0",
        "activity",
        "tourism_activity",
        95,
    ),
    "tourist_entertainment_restaurants": KrmoisLicenseFeatureMapping(
        "tourist_entertainment_restaurants",
        PlaceCategoryCode.FOOD_RESTAURANT_BAR.value,
        "bar",
        "#9B2C2C",
        "bar",
        "food",
        75,
    ),
    "tourist_pensions": KrmoisLicenseFeatureMapping(
        "tourist_pensions",
        PlaceCategoryCode.LODGING_PENSION_TOURISM.value,
        "lodging",
        "#4A5568",
        "pension",
        "lodging",
        95,
    ),
    "tourist_performance_halls": KrmoisLicenseFeatureMapping(
        "tourist_performance_halls",
        PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL_TOURISM.value,
        "theatre",
        "#2B6CB0",
        "culture_facility",
        "culture_leisure",
        95,
    ),
    "tourist_railways": KrmoisLicenseFeatureMapping(
        "tourist_railways",
        PlaceCategoryCode.TOURISM_ACTIVITY_RAIL_CABLE.value,
        "rail",
        "#2B6CB0",
        "activity",
        "tourism_activity",
        95,
    ),
    "tourist_restaurants": KrmoisLicenseFeatureMapping(
        "tourist_restaurants",
        PlaceCategoryCode.FOOD_RESTAURANT.value,
        "restaurant",
        "#C2410C",
        "restaurant",
        "food",
        95,
    ),
    "tourist_theater_entertainment": KrmoisLicenseFeatureMapping(
        "tourist_theater_entertainment",
        PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL_TOURISM.value,
        "theatre",
        "#2B6CB0",
        "culture_facility",
        "culture_leisure",
        75,
    ),
    "traditional_temples": KrmoisLicenseFeatureMapping(
        "traditional_temples",
        PlaceCategoryCode.TOURISM_HERITAGE_TEMPLE.value,
        "religious-buddhist",
        "#805AD5",
        "heritage",
        "heritage",
        95,
    ),
    "yacht_marinas": KrmoisLicenseFeatureMapping(
        "yacht_marinas",
        PlaceCategoryCode.TOURISM_ACTIVITY_LEISURE_SPORTS.value,
        "harbor",
        "#2F855A",
        "activity",
        "sports_leisure",
        80,
    ),
}

KRMOIS_LICENSE_PROMOTED_SERVICE_SLUGS = tuple(
    sorted(KRMOIS_LICENSE_PROMOTION_MAPPINGS)
)


@dataclass(frozen=True)
class SkippedKrmoisLicenseRecord:
    service_slug: str | None
    management_number: str | None
    reason: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class KrmoisLicenseFeatureBundle:
    feature: Feature
    place_detail: PlaceDetail
    address_match_report: AddressMatchReport


@dataclass(frozen=True)
class KrmoisLicenseFeatureEtlResult:
    dataset_key: str
    features: tuple[Feature, ...]
    place_details: tuple[PlaceDetail, ...]
    address_match_reports: tuple[AddressMatchReport, ...]
    skipped_records: tuple[SkippedKrmoisLicenseRecord, ...] = ()

    @property
    def item_count(self) -> int:
        return len(self.features)


@dataclass(frozen=True)
class KrmoisLicenseFeatureDbEtlResult:
    collection: KrmoisLicenseFeatureEtlResult
    load: FeatureDbLoadResult
    deleted_features: int = 0
    source_sync_result: Any | None = None

    @property
    def item_count(self) -> int:
        return self.collection.item_count


@dataclass(frozen=True)
class KrmoisLicenseFeatureLoadResources:
    source_db_session: Any
    feature_session: Any | None = None
    file_client: Any | None = None
    reverse_geocoder: ReverseGeocoder | None = None
    kraddr_geo_store: Any | None = None
    kraddr_geo_database_path: str | None = None
    kraddr_geo_store_kwargs: Mapping[str, Any] | None = None
    kraddr_geo_fallback: bool = True
    kraddr_geo_max_distance_m: float | None = 50.0


def collect_krmois_license_features(
    records: Iterable[Any],
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KrmoisLicenseFeatureEtlResult:
    """Convert open MOIS `PlaceRecord` rows into TripMate map features."""

    features_result: list[Feature] = []
    place_details: list[PlaceDetail] = []
    address_match_reports: list[AddressMatchReport] = []
    skipped_records: list[SkippedKrmoisLicenseRecord] = []

    for record in records:
        place = _place_record(record)
        bundle = krmois_license_place_to_feature_bundle(
            place,
            collected_at=collected_at,
            reverse_geocoder=reverse_geocoder,
        )
        if isinstance(bundle, SkippedKrmoisLicenseRecord):
            skipped_records.append(bundle)
            continue
        features_result.append(bundle.feature)
        place_details.append(bundle.place_detail)
        address_match_reports.append(bundle.address_match_report)

    return KrmoisLicenseFeatureEtlResult(
        dataset_key=KRMOIS_LICENSE_FEATURE_DATASET_KEY,
        features=tuple(features_result),
        place_details=tuple(place_details),
        address_match_reports=tuple(address_match_reports),
        skipped_records=tuple(skipped_records),
    )


def krmois_license_place_to_feature_bundle(
    place: Any,
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KrmoisLicenseFeatureBundle | SkippedKrmoisLicenseRecord:
    """Normalize one stable `python-krmois-api` `PlaceRecord` into a feature."""

    service_slug = _optional_text(getattr(place, "service_slug", None))
    management_number = _optional_text(getattr(place, "mng_no", None))
    raw = _source_summary(place)
    if service_slug is None:
        return SkippedKrmoisLicenseRecord(None, management_number, "missing service_slug", raw)
    if service_slug in KRMOIS_EXCLUDED_SERVICE_SLUGS:
        return SkippedKrmoisLicenseRecord(
            service_slug,
            management_number,
            "excluded service_slug",
            raw,
        )
    if getattr(place, "is_open", None) is not True:
        return SkippedKrmoisLicenseRecord(
            service_slug,
            management_number,
            "not open",
            raw,
        )
    mapping = KRMOIS_LICENSE_PROMOTION_MAPPINGS.get(service_slug)
    if mapping is None:
        return SkippedKrmoisLicenseRecord(
            service_slug,
            management_number,
            "no travel feature mapping",
            raw,
        )
    if management_number is None:
        return SkippedKrmoisLicenseRecord(
            service_slug,
            None,
            "missing management number",
            raw,
        )
    name = _optional_text(getattr(place, "place_name", None))
    if name is None:
        return SkippedKrmoisLicenseRecord(
            service_slug,
            management_number,
            "missing place name",
            raw,
        )

    coordinate = _coordinate_from_place(place)
    address_enrichment = enrich_address_from_coordinate(
        address=_address_from_place(place),
        coordinate=coordinate,
        raw=_address_raw(place),
        reverse_geocoder=reverse_geocoder,
        source_label=KRMOIS_LICENSE_FEATURE_DATASET_KEY,
        source_entity_id=management_number,
    )
    address = address_enrichment.address
    raw_payload_hash = make_payload_hash(raw, length=32)
    feature_id = make_feature_id(
        provider=KRMOIS_PROVIDER,
        source_type=service_slug,
        source_natural_key=management_number,
        kind=FeatureKind.PLACE,
        category=mapping.category,
        legal_dong_code=address.legal_dong_code,
    )
    detail_payload = _feature_detail_payload(
        place,
        mapping=mapping,
        address_match_report=address_enrichment.report,
    )
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=name,
        coord=coordinate,
        address=address,
        category=mapping.category,
        marker_icon=mapping.marker_icon,
        marker_color=mapping.marker_color,
        detail=detail_payload,
        raw_refs=[
            RawDataRef(
                provider=KRMOIS_PROVIDER,
                dataset_key=KRMOIS_LICENSE_FEATURE_DATASET_KEY,
                source_entity_id=management_number,
                source_role=SourceRole.PRIMARY,
                fetched_at=collected_at,
                payload_hash=raw_payload_hash,
            )
        ],
    )
    place_detail = PlaceDetail(
        feature_id=feature_id,
        place_kind=mapping.place_kind,
        phones=[tel] if (tel := _optional_text(getattr(place, "telno", None))) else [],
        facility_info=_facility_info(place, mapping=mapping),
        license_date=getattr(place, "license_date", None),
        payload=detail_payload,
    )
    return KrmoisLicenseFeatureBundle(
        feature=feature,
        place_detail=place_detail,
        address_match_report=address_enrichment.report,
    )


def load_krmois_license_feature_result(
    session: Any,
    result: KrmoisLicenseFeatureEtlResult,
    *,
    prune_existing: bool = False,
) -> KrmoisLicenseFeatureDbEtlResult:
    """Load KRMOIS feature rows and optionally prune stale/closed features."""

    deleted_features = 0
    if prune_existing:
        deleted_features = delete_krmois_license_features_not_in(
            session,
            keep_feature_ids=(feature.feature_id for feature in result.features),
        )
    load_result = load_feature_rows(
        session,
        feature_items=result.features,
        place_detail_items=result.place_details,
    )
    return KrmoisLicenseFeatureDbEtlResult(
        collection=result,
        load=load_result,
        deleted_features=deleted_features,
    )


def collect_and_load_krmois_license_features(
    session: Any,
    records: Iterable[Any],
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
    prune_existing: bool = False,
) -> KrmoisLicenseFeatureDbEtlResult:
    """Collect open MOIS license rows and stage feature rows in one call."""

    collection = collect_krmois_license_features(
        records,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )
    return load_krmois_license_feature_result(
        session,
        collection,
        prune_existing=prune_existing,
    )


def delete_krmois_license_features_not_in(
    session: Any,
    *,
    keep_feature_ids: Iterable[str],
) -> int:
    """Delete KRMOIS-managed features absent from the latest open snapshot."""

    keep = set(keep_feature_ids)
    stale_feature_ids = [
        row["feature_id"]
        for row in session.execute(
            select(features.c.feature_id, features.c.detail, features.c.raw_refs)
        ).mappings()
        if _is_krmois_feature_row(row) and row["feature_id"] not in keep
    ]
    if not stale_feature_ids:
        return 0
    session.execute(
        feature_place_details.delete().where(
            feature_place_details.c.feature_id.in_(stale_feature_ids)
        )
    )
    session.execute(features.delete().where(features.c.feature_id.in_(stale_feature_ids)))
    return len(stale_feature_ids)


def delete_krmois_license_features_for_records(
    session: Any,
    records: Iterable[Any],
) -> int:
    """Delete feature rows matching closed/cancelled MOIS source identities."""

    source_keys = {
        (
            _optional_text(getattr(place := _place_record(record), "service_slug", None)),
            _optional_text(getattr(place, "mng_no", None)),
        )
        for record in records
    }
    source_keys.discard((None, None))
    if not source_keys:
        return 0

    feature_ids = [
        row["feature_id"]
        for row in session.execute(
            select(features.c.feature_id, features.c.detail, features.c.raw_refs)
        ).mappings()
        if _krmois_source_key(row.get("detail")) in source_keys
    ]
    if not feature_ids:
        return 0
    session.execute(
        feature_place_details.delete().where(feature_place_details.c.feature_id.in_(feature_ids))
    )
    session.execute(features.delete().where(features.c.feature_id.in_(feature_ids)))
    return len(feature_ids)


def load_krmois_license_features(
    resource: Any,
    run: DagsterEtlRun,
) -> KrmoisLicenseFeatureEtlResult | KrmoisLicenseFeatureDbEtlResult:
    """TripMate Dagster op body for the weekly KRMOIS source+feature refresh."""

    config = run.op_config
    source_db_session, feature_session, file_client, reverse_geocoder = (
        _resolve_krmois_resources(resource)
    )
    service_slugs = _service_slugs_config(config) or KRMOIS_LICENSE_PROMOTED_SERVICE_SLUGS
    batch_size = _optional_int(config.get("batch_size")) or KRMOIS_LICENSE_DEFAULT_BATCH_SIZE
    sync_source_db = _optional_bool(config.get("sync_source_db"), default=True)
    prune_existing = _optional_bool(config.get("prune_existing"), default=True)

    source_sync_result: Any | None = None
    if sync_source_db:
        if file_client is None:
            raise ValueError("KRMOIS source DB sync requires LocalDataFileClient resource")
        source_sync_result = _sync_krmois_source_db(
            source_db_session,
            file_client,
            service_slugs=service_slugs,
            batch_size=batch_size,
        )

    records = _iter_open_krmois_records(
        source_db_session,
        service_slugs=service_slugs,
        batch_size=batch_size,
    )
    if feature_session is None:
        return collect_krmois_license_features(
            records,
            collected_at=run.collected_at,
            reverse_geocoder=reverse_geocoder,
        )

    result = collect_and_load_krmois_license_features(
        feature_session,
        records,
        collected_at=run.collected_at,
        reverse_geocoder=reverse_geocoder,
        prune_existing=prune_existing,
    )
    return KrmoisLicenseFeatureDbEtlResult(
        collection=result.collection,
        load=result.load,
        deleted_features=result.deleted_features,
        source_sync_result=source_sync_result,
    )


def krmois_license_feature_full_update_identity(
    _session: Any,
    _dataset_key: str,
    execution: DagsterEtlExecution,
) -> EtlRunIdentity:
    logical_date = execution.logical_datetime_kst.date()
    return EtlRunIdentity(
        run_key=f"{logical_date:%Y%m%d}-weekly-full-update",
        run_type=execution.run_type,
        trigger_date=logical_date,
    )


krmois_license_feature_full_update_job_spec = EtlJobSpec(
    job_name="krmois_license_feature_full_update",
    op_name="collect_krmois_license_features",
    dataset_key=KRMOIS_LICENSE_FEATURE_DATASET_KEY,
    description=(
        "Refresh python-krmois-api localdata source DB and rebuild open travel "
        "features from promoted KRMOIS license rows."
    ),
    tags=(
        f"provider:{KRMOIS_PROVIDER}",
        "feature:place",
        "source:krmois",
        "full_update",
        "schedule:weekly",
        "source_db:python-krmois-api",
        "closed:delete",
    ),
    loader=load_krmois_license_features,
    success_message="KRMOIS license feature weekly full update completed.",
    failure_message="KRMOIS license feature weekly full update failed.",
    identity_resolver=krmois_license_feature_full_update_identity,
    schedule_enabled=schedule_is_enabled_by_default,
)


def _place_record(record: Any) -> Any:
    if hasattr(record, "service_slug") and hasattr(record, "mng_no"):
        return record
    try:
        from mois import record_to_place_record
    except ImportError as exc:
        raise TypeError(
            "KRMOIS ETL requires python-krmois-api PlaceRecord or LocalDataRecord"
        ) from exc
    return record_to_place_record(record)


def _coordinate_from_place(place: Any) -> Coordinate | None:
    lat = _optional_float(getattr(place, "lat", None))
    lon = _optional_float(getattr(place, "lon", None))
    if lat is None or lon is None:
        return None
    return Coordinate(lat=lat, lon=lon)


def _address_from_place(place: Any) -> Address:
    mapping = {
        "road_address": _optional_text(getattr(place, "road_address", None)),
        "jibun_address": _optional_text(getattr(place, "lot_address", None)),
        "postal_code": _optional_text(
            getattr(place, "road_zip", None) or getattr(place, "lot_zip", None)
        ),
        "legal_dong_code": _optional_text(getattr(place, "legal_dong_code", None)),
        "road_name_code": _optional_text(getattr(place, "road_name_code", None)),
        "building_management_number": _optional_text(
            getattr(place, "building_management_number", None)
        ),
    }
    return Address.from_mapping(mapping) or Address(
        address=mapping["road_address"] or mapping["jibun_address"]
    )


def _address_raw(place: Any) -> dict[str, Any]:
    data = _mapping(getattr(place, "data", None))
    raw = _mapping(getattr(place, "raw", None))
    return {
        **raw,
        **data,
        "LEGAL_DONG_CD": _optional_text(getattr(place, "legal_dong_code", None)),
        "RN_MGT_SN": _optional_text(getattr(place, "road_name_code", None)),
        "BD_MGT_SN": _optional_text(getattr(place, "building_management_number", None)),
        "road_address": _optional_text(getattr(place, "road_address", None)),
        "jibun_address": _optional_text(getattr(place, "lot_address", None)),
    }


def _feature_detail_payload(
    place: Any,
    *,
    mapping: KrmoisLicenseFeatureMapping,
    address_match_report: AddressMatchReport,
) -> dict[str, Any]:
    address_codes = _address_code_detail(place, address_match_report=address_match_report)
    return {
        "selected_source": _selected_source(place),
        "selected_coordinate": _selected_coordinate(place),
        "category_confidence": mapping.category_confidence,
        "category_mapping": {
            "service_slug": mapping.service_slug,
            "feature_group": mapping.feature_group,
            "kraddr_category": mapping.category,
        },
        "match_level": address_match_report.match_level,
        "visible_status": "visible",
        "visible": True,
        "license_status": {
            "status_code": _optional_text(getattr(place, "status_code", None)),
            "status_name": _optional_text(getattr(place, "status_name", None)),
            "detail_status_code": _optional_text(getattr(place, "detail_status_code", None)),
            "detail_status_name": _optional_text(getattr(place, "detail_status_name", None)),
            "is_open": getattr(place, "is_open", None),
        },
        "license_dates": {
            "license_date": _iso_value(getattr(place, "license_date", None)),
            "designation_date": _iso_value(getattr(place, "designation_date", None)),
            "data_updated_at": _iso_value(getattr(place, "data_updated_at", None)),
            "source_modified_at": _iso_value(getattr(place, "source_modified_at", None)),
        },
        "address_codes": address_codes,
    }


def _selected_source(place: Any) -> dict[str, Any]:
    return {
        "provider": KRMOIS_PROVIDER,
        "source_db": "python-krmois-api",
        "dataset_key": KRMOIS_LICENSE_FEATURE_DATASET_KEY,
        "service_slug": _optional_text(getattr(place, "service_slug", None)),
        "mng_no": _optional_text(getattr(place, "mng_no", None)),
        "title": _optional_text(getattr(place, "title", None)),
        "opn_authority_code": _optional_text(getattr(place, "opn_authority_code", None)),
    }


def _selected_coordinate(place: Any) -> dict[str, Any] | None:
    lon = _optional_float(getattr(place, "lon", None))
    lat = _optional_float(getattr(place, "lat", None))
    if lon is None or lat is None:
        return None
    return {
        "source": "krmois_localdata",
        "crs": "EPSG:4326",
        "lon": lon,
        "lat": lat,
        "source_crs": "EPSG:5174",
        "source_x": _optional_float(getattr(place, "source_x", None)),
        "source_y": _optional_float(getattr(place, "source_y", None)),
    }


def _address_code_detail(
    place: Any,
    *,
    address_match_report: AddressMatchReport,
) -> dict[str, Any]:
    return {
        "original_legal_dong_code": _optional_text(getattr(place, "legal_dong_code", None)),
        "original_road_name_code": _optional_text(getattr(place, "road_name_code", None)),
        "original_building_management_number": _optional_text(
            getattr(place, "building_management_number", None)
        ),
        "enriched_legal_dong_code": address_match_report.legal_dong_code_after,
        "match_level": address_match_report.match_level,
        "match_confidence": address_match_report.confidence,
        "code_source": address_match_report.code_source,
        "notes": list(address_match_report.notes),
    }


def _facility_info(
    place: Any,
    *,
    mapping: KrmoisLicenseFeatureMapping,
) -> dict[str, Any]:
    common = _without_none(
        {
            "feature_group": mapping.feature_group,
            "business_type_name": _optional_text(getattr(place, "business_type_name", None)),
            "subtype_name": _optional_text(getattr(place, "subtype_name", None)),
            "facility_total_scale": _optional_text(
                getattr(place, "facility_total_scale", None)
            ),
            "facility_area": _optional_float(getattr(place, "facility_area", None)),
            "total_area": _optional_float(getattr(place, "total_area", None)),
            "multi_use_business_place_yn": _optional_text(
                getattr(place, "multi_use_business_place_yn", None)
            ),
            "building_usage_name": _optional_text(getattr(place, "building_usage_name", None)),
            "ground_floor_count": _optional_int(getattr(place, "ground_floor_count", None)),
            "underground_floor_count": _optional_int(
                getattr(place, "underground_floor_count", None)
            ),
            "total_floor_count": _optional_int(getattr(place, "total_floor_count", None)),
        }
    )
    if mapping.feature_group == "medical":
        common.update(
            _without_none(
                {
                    "sickbed_count": _optional_int(getattr(place, "sickbed_count", None)),
                    "bed_count": _optional_int(getattr(place, "bed_count", None)),
                    "healthcare_worker_count": _optional_int(
                        getattr(place, "healthcare_worker_count", None)
                    ),
                    "hospital_room_count": _optional_int(
                        getattr(place, "hospital_room_count", None)
                    ),
                    "medical_institution_type_name": _optional_text(
                        getattr(place, "medical_institution_type_name", None)
                    ),
                    "medical_subject_names": _optional_text(
                        getattr(place, "medical_subject_names", None)
                    ),
                }
            )
        )
    elif mapping.feature_group == "food":
        common.update(
            _without_none(
                {
                    "sanitation_business_status_name": _optional_text(
                        getattr(place, "sanitation_business_status_name", None)
                    ),
                    "water_supply_facility_type_name": _optional_text(
                        getattr(place, "water_supply_facility_type_name", None)
                    ),
                }
            )
        )
    elif mapping.feature_group in {"culture_leisure", "sports_leisure", "tourism_activity"}:
        common.update(
            _without_none(
                {
                    "culture_sports_business_type_name": _optional_text(
                        getattr(place, "culture_sports_business_type_name", None)
                    ),
                    "designation_date": _iso_value(getattr(place, "designation_date", None)),
                }
            )
        )
    elif mapping.feature_group == "retail":
        common.update(
            _without_none(
                {
                    "sales_method_name": _optional_text(
                        getattr(place, "sales_method_name", None)
                    ),
                }
            )
        )
    return common


def _source_summary(place: Any) -> dict[str, Any]:
    return _without_none(
        {
            "service_slug": _optional_text(getattr(place, "service_slug", None)),
            "mng_no": _optional_text(getattr(place, "mng_no", None)),
            "category": _optional_text(getattr(place, "category", None)),
            "title": _optional_text(getattr(place, "title", None)),
            "place_name": _optional_text(getattr(place, "place_name", None)),
            "status_code": _optional_text(getattr(place, "status_code", None)),
            "status_name": _optional_text(getattr(place, "status_name", None)),
            "detail_status_code": _optional_text(getattr(place, "detail_status_code", None)),
            "detail_status_name": _optional_text(getattr(place, "detail_status_name", None)),
            "is_open": getattr(place, "is_open", None),
            "license_date": _iso_value(getattr(place, "license_date", None)),
            "closed_date": _iso_value(getattr(place, "closed_date", None)),
            "license_cancelled_date": _iso_value(
                getattr(place, "license_cancelled_date", None)
            ),
            "road_address": _optional_text(getattr(place, "road_address", None)),
            "lot_address": _optional_text(getattr(place, "lot_address", None)),
            "lon": _optional_float(getattr(place, "lon", None)),
            "lat": _optional_float(getattr(place, "lat", None)),
        }
    )


def _is_krmois_feature_row(row: Mapping[str, Any]) -> bool:
    detail = row.get("detail")
    if _krmois_source_key(detail) != (None, None):
        return True
    raw_refs = row.get("raw_refs") or []
    if isinstance(raw_refs, list):
        return any(
            isinstance(ref, Mapping) and ref.get("provider") == KRMOIS_PROVIDER
            for ref in raw_refs
        )
    return False


def _krmois_source_key(detail: Any) -> tuple[str | None, str | None]:
    if not isinstance(detail, Mapping):
        return (None, None)
    selected_source = detail.get("selected_source")
    if not isinstance(selected_source, Mapping):
        return (None, None)
    if selected_source.get("provider") != KRMOIS_PROVIDER:
        return (None, None)
    return (
        _optional_text(selected_source.get("service_slug")),
        _optional_text(selected_source.get("mng_no")),
    )


def _iter_open_krmois_records(
    source_db_session: Any,
    *,
    service_slugs: tuple[str, ...],
    batch_size: int,
) -> Iterable[Any]:
    try:
        from mois import iter_open_place_records
    except ImportError as exc:
        raise RuntimeError("python-krmois-api is required for KRMOIS source DB reads") from exc
    return iter_open_place_records(
        source_db_session,
        service_slugs=service_slugs,
        batch_size=batch_size,
    )


def _sync_krmois_source_db(
    source_db_session: Any,
    file_client: Any,
    *,
    service_slugs: tuple[str, ...],
    batch_size: int,
) -> Any:
    try:
        from mois import sync_localdata_source_db
    except ImportError as exc:
        raise RuntimeError("python-krmois-api is required for KRMOIS source DB sync") from exc
    return sync_localdata_source_db(
        source_db_session,
        file_client,
        service_slugs=service_slugs,
        batch_size=batch_size,
        sync_kind=KRMOIS_LICENSE_SOURCE_DB_SYNC_KIND,
    )


def _resolve_krmois_resources(
    resource: Any,
) -> tuple[Any, Any | None, Any | None, ReverseGeocoder | None]:
    if isinstance(resource, Mapping):
        source_db_session = resource.get("source_db_session") or resource.get(
            "krmois_source_db_session"
        )
        feature_session = resource.get("feature_session") or resource.get("session")
        file_client = resource.get("file_client") or resource.get("krmois_file_client")
        reverse_geocoder = resolve_reverse_geocoder(resource)
    else:
        source_db_session = getattr(resource, "source_db_session", None) or getattr(
            resource,
            "krmois_source_db_session",
            None,
        )
        feature_session = getattr(resource, "feature_session", None) or getattr(
            resource,
            "session",
            None,
        )
        file_client = getattr(resource, "file_client", None) or getattr(
            resource,
            "krmois_file_client",
            None,
        )
        reverse_geocoder = resolve_reverse_geocoder(resource)
    if source_db_session is None:
        raise ValueError("KRMOIS ETL resource must provide source_db_session")
    return source_db_session, feature_session, file_client, reverse_geocoder


def _service_slugs_config(config: Mapping[str, object]) -> tuple[str, ...] | None:
    value = config.get("service_slugs")
    if value is None:
        return None
    if isinstance(value, str):
        slugs = tuple(part.strip() for part in value.split(",") if part.strip())
    elif isinstance(value, list | tuple):
        slugs = tuple(str(part).strip() for part in value if str(part).strip())
    else:
        raise TypeError("service_slugs must be a comma-separated string or sequence")
    unknown = sorted(
        slug
        for slug in slugs
        if slug not in KRMOIS_LICENSE_PROMOTION_MAPPINGS
        and slug not in KRMOIS_EXCLUDED_SERVICE_SLUGS
    )
    if unknown:
        raise ValueError(f"unknown KRMOIS service slugs: {', '.join(unknown)}")
    return tuple(slug for slug in slugs if slug in KRMOIS_LICENSE_PROMOTION_MAPPINGS)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _without_none(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _iso_value(value: Any) -> str | None:
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _optional_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")
