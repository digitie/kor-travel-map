from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeAlias

from kraddr.base import (
    Address,
    AddressCodeSet,
    AddressRegion,
    PlaceCoordinate,
    RoadNameAddress,
)

AddressMatchLevel: TypeAlias = Literal[
    "address_geocode_legal_dong",
    "legal_dong_exact",
    "coordinate_legal_dong",
    "legal_dong_conflict",
    "source_legal_dong",
    "provider_code_converted",
    "sigungu_code_only",
    "address_text_match",
    "address_text_review",
    "address_text_only",
    "coordinate_only",
    "not_geocoded",
    "no_address",
]
ReverseGeocoder: TypeAlias = Callable[
    [PlaceCoordinate],
    Address | Mapping[str, Any] | object | None,
]
AddressGeocoder: TypeAlias = Callable[
    [Address],
    PlaceCoordinate | Mapping[str, Any] | object | None,
]


@dataclass(frozen=True)
class AddressMatchReport:
    """Review information for coordinate-based address enrichment."""

    source_label: str
    source_entity_id: str | None
    input_address: str | None
    geocoded_address: str | None
    legal_dong_code_before: str | None
    legal_dong_code_after: str | None
    match_level: AddressMatchLevel
    confidence: int
    code_source: str | None = None
    provider_code_type: str | None = None
    provider_code_value: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class AddressEnrichment:
    address: Address
    report: AddressMatchReport
    geocoded_address: Address | None = None
    coordinate: PlaceCoordinate | None = None
    geocoded_coordinate: PlaceCoordinate | None = None


@dataclass
class KrAddrGeoReverseGeocoder:
    """Callable reverse geocoder backed by ``python-kraddr-geo``.

    `python-krtour-map` only imports `kraddr.geo` lazily. If that store is
    configured to fallback to VWorld, the fallback remains owned by
    `python-kraddr-geo`; this package never imports `python-vworld-api`.
    """

    store: Any | None = None
    database_path: str | Path | None = None
    store_kwargs: Mapping[str, Any] | None = None
    fallback: bool = True
    max_distance_m: float | None = 50.0

    _owned_store: Any | None = None

    def __call__(self, coordinate: PlaceCoordinate) -> Address | None:
        store = self._resolve_store()
        request = {
            "x": _coordinate_lon(coordinate),
            "y": _coordinate_lat(coordinate),
            "crs": "EPSG:4326",
            "type": "both",
            "max_distance_m": self.max_distance_m,
        }
        try:
            result = store.get_address(request, fallback=self.fallback)
        except TypeError:
            result = store.get_address(request)
        return _address_from_geocoder_result(result)

    def close(self) -> None:
        store = self._owned_store
        self._owned_store = None
        close = getattr(store, "close", None)
        if callable(close):
            close()

    def _resolve_store(self) -> Any:
        if self.store is not None:
            return self.store
        if self._owned_store is not None:
            return self._owned_store
        if self.database_path is None:
            raise ValueError("kraddr-geo reverse geocoder requires a store or database_path")
        try:
            from kraddr.geo import SpatialiteAddressStore
        except ImportError as exc:  # pragma: no cover - depends on optional package install.
            raise RuntimeError(
                "python-kraddr-geo is required for built-in reverse geocoding. "
                "Install the geo extra or pass an explicit reverse_geocoder callable."
            ) from exc
        self._owned_store = SpatialiteAddressStore(
            self.database_path,
            **dict(self.store_kwargs or {}),
        )
        return self._owned_store


def kraddr_geo_reverse_geocoder(
    *,
    store: Any | None = None,
    database_path: str | Path | None = None,
    store_kwargs: Mapping[str, Any] | None = None,
    fallback: bool = True,
    max_distance_m: float | None = 50.0,
) -> KrAddrGeoReverseGeocoder:
    """Build the standard kraddr-geo-backed reverse geocoder callable."""

    return KrAddrGeoReverseGeocoder(
        store=store,
        database_path=database_path,
        store_kwargs=store_kwargs,
        fallback=fallback,
        max_distance_m=max_distance_m,
    )


@dataclass
class KrAddrGeoAddressGeocoder:
    """Callable address geocoder backed by ``python-kraddr-geo``."""

    store: Any | None = None
    database_path: str | Path | None = None
    store_kwargs: Mapping[str, Any] | None = None
    fallback: bool = True
    limit: int = 1

    _owned_store: Any | None = None

    def __call__(self, address: Address) -> PlaceCoordinate | Mapping[str, Any] | object | None:
        query = address.display_address
        if not query:
            return None
        store = self._resolve_store()
        request = {
            "query": query,
            "crs": "EPSG:4326",
            "type": "both",
            "limit": self.limit,
        }
        try:
            candidates = store.get_coord(request, fallback=self.fallback)
        except TypeError:
            candidates = store.get_coord(request)
        if candidates is None:
            return None
        if isinstance(candidates, list | tuple):
            return candidates[0] if candidates else None
        return candidates

    def close(self) -> None:
        store = self._owned_store
        self._owned_store = None
        close = getattr(store, "close", None)
        if callable(close):
            close()

    def _resolve_store(self) -> Any:
        if self.store is not None:
            return self.store
        if self._owned_store is not None:
            return self._owned_store
        if self.database_path is None:
            raise ValueError("kraddr-geo address geocoder requires a store or database_path")
        try:
            from kraddr.geo import SpatialiteAddressStore
        except ImportError as exc:  # pragma: no cover - depends on optional package install.
            raise RuntimeError(
                "python-kraddr-geo is required for built-in address geocoding. "
                "Install the geo extra or pass an explicit address_geocoder callable."
            ) from exc
        self._owned_store = SpatialiteAddressStore(
            self.database_path,
            **dict(self.store_kwargs or {}),
        )
        return self._owned_store


def kraddr_geo_address_geocoder(
    *,
    store: Any | None = None,
    database_path: str | Path | None = None,
    store_kwargs: Mapping[str, Any] | None = None,
    fallback: bool = True,
    limit: int = 1,
) -> KrAddrGeoAddressGeocoder:
    """Build the standard kraddr-geo-backed address geocoder callable."""

    return KrAddrGeoAddressGeocoder(
        store=store,
        database_path=database_path,
        store_kwargs=store_kwargs,
        fallback=fallback,
        limit=limit,
    )


def resolve_reverse_geocoder(resource: Any) -> ReverseGeocoder | None:
    """Return an explicit reverse geocoder or derive one from kraddr-geo settings.

    Supported resource keys/attributes:

    - `reverse_geocoder`: already-built callable
    - `kraddr_geo_reverse_geocoder`: already-built callable
    - `kraddr_geo_store`: `SpatialiteAddressStore` or compatible object
    - `kraddr_geo_database_path` / `kraddr_geo_db_path`: local SQLite path
    - `kraddr_geo_store_kwargs`: kwargs forwarded to `SpatialiteAddressStore`
    """

    direct = _resource_value(resource, "reverse_geocoder")
    if callable(direct):
        return direct

    direct = _resource_value(resource, "kraddr_geo_reverse_geocoder")
    if callable(direct):
        return direct

    store = _resource_value(resource, "kraddr_geo_store") or _resource_value(
        resource,
        "address_store",
    )
    database_path = _resource_value(resource, "kraddr_geo_database_path") or _resource_value(
        resource,
        "kraddr_geo_db_path",
    )
    if store is None and database_path is None:
        return None

    store_kwargs = _resource_value(resource, "kraddr_geo_store_kwargs")
    if store_kwargs is not None and not isinstance(store_kwargs, Mapping):
        raise TypeError("kraddr_geo_store_kwargs must be a mapping")

    fallback = _resource_bool(resource, "kraddr_geo_fallback", default=True)
    max_distance_m = _resource_float(resource, "kraddr_geo_max_distance_m", default=50.0)
    return kraddr_geo_reverse_geocoder(
        store=store,
        database_path=database_path,
        store_kwargs=store_kwargs,
        fallback=fallback,
        max_distance_m=max_distance_m,
    )


def resolve_address_geocoder(resource: Any) -> AddressGeocoder | None:
    """Return an explicit address geocoder or derive one from kraddr-geo settings."""

    direct = _resource_value(resource, "address_geocoder")
    if callable(direct):
        return direct

    direct = _resource_value(resource, "kraddr_geo_address_geocoder")
    if callable(direct):
        return direct

    store = _resource_value(resource, "kraddr_geo_store") or _resource_value(
        resource,
        "address_store",
    )
    database_path = _resource_value(resource, "kraddr_geo_database_path") or _resource_value(
        resource,
        "kraddr_geo_db_path",
    )
    if store is None and database_path is None:
        return None

    store_kwargs = _resource_value(resource, "kraddr_geo_store_kwargs")
    if store_kwargs is not None and not isinstance(store_kwargs, Mapping):
        raise TypeError("kraddr_geo_store_kwargs must be a mapping")

    fallback = _resource_bool(resource, "kraddr_geo_fallback", default=True)
    limit = int(_resource_float(resource, "kraddr_geo_geocode_limit", default=1) or 1)
    return kraddr_geo_address_geocoder(
        store=store,
        database_path=database_path,
        store_kwargs=store_kwargs,
        fallback=fallback,
        limit=limit,
    )


def enrich_address_from_coordinate(
    *,
    address: Address | Mapping[str, Any] | None = None,
    coordinate: PlaceCoordinate | None = None,
    raw: Mapping[str, Any] | None = None,
    address_geocoder: AddressGeocoder | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
    source_label: str,
    source_entity_id: str | None = None,
) -> AddressEnrichment:
    """Normalize an address and optionally enrich it from a coordinate.

    `python-krtour-map` does not wrap provider-specific geocoding clients. It can
    call an injected callable, or loaders can derive one from `python-kraddr-geo`
    resources. Any VWorld fallback is owned by `python-kraddr-geo`.
    """

    raw_mapping = dict(raw or {})
    original_address = coerce_address(address, raw_mapping)
    source_address = original_address or Address()
    notes: list[str] = []
    provider_code_type, provider_code_value = provider_address_code(raw_mapping)
    before = source_address.legal_dong_code
    code_source: str | None = None
    match_level: AddressMatchLevel = "no_address"
    confidence = 0

    source_codes = address_code_set_from_raw(raw_mapping, notes=notes)
    if source_codes is not None and source_codes.has_any_code:
        source_address, derived_level = address_with_code_set(source_address, source_codes)
        after_source_code = source_address.legal_dong_code
        if after_source_code and after_source_code != before:
            code_source = "source_address_code"
            match_level = derived_level
            confidence = 80 if derived_level == "provider_code_converted" else 65

    geocoded_coordinate, address_geocode_address = _call_address_geocoder(
        source_address,
        coordinate,
        address_geocoder,
        notes=notes,
    )
    if coordinate is None and geocoded_coordinate is not None:
        coordinate = geocoded_coordinate
        notes.append("coordinate geocoded from address text")
    if address_geocode_address is not None:
        source_address = merge_address_enrichment(source_address, address_geocode_address)
        if address_geocode_address.legal_dong_code is not None:
            match_level = "address_geocode_legal_dong"
            confidence = max(confidence, 85)
            code_source = "address_geocode"

    geocoded_address = _call_reverse_geocoder(coordinate, reverse_geocoder, notes=notes)
    if geocoded_address is not None:
        source_address = merge_address_enrichment(source_address, geocoded_address)
        geocoded_code = geocoded_address.legal_dong_code
        if geocoded_code is not None:
            if before == geocoded_code:
                match_level = "legal_dong_exact"
                confidence = 100
            elif before is not None and before != geocoded_code:
                match_level = "legal_dong_conflict"
                confidence = 55
                notes.append("source legal_dong_code differs from coordinate reverse geocode")
            elif source_address.display_address:
                match_level = "coordinate_legal_dong"
                confidence = 90
            else:
                match_level = "coordinate_only"
                confidence = 80
            code_source = "coordinate_reverse_geocode"
        elif _same_address_text(source_address.display_address, geocoded_address.display_address):
            match_level = "address_text_match"
            confidence = max(confidence, 70)
        elif source_address.display_address and geocoded_address.display_address:
            match_level = "address_text_review"
            confidence = max(confidence, 50)
            notes.append("address text and coordinate geocode should be reviewed")

    after = source_address.legal_dong_code
    if match_level == "no_address":
        if after is not None:
            match_level = "source_legal_dong"
            confidence = 75
        elif source_address.display_address:
            match_level = "address_text_only"
            confidence = 40
        elif coordinate is not None and reverse_geocoder is None:
            match_level = "not_geocoded"
            confidence = 0

    if provider_code_type and code_source is None:
        notes.append("provider-specific address code was retained in raw payload only")

    return AddressEnrichment(
        address=source_address,
        geocoded_address=geocoded_address,
        coordinate=coordinate,
        geocoded_coordinate=geocoded_coordinate,
        report=AddressMatchReport(
            source_label=source_label,
            source_entity_id=source_entity_id,
            input_address=(
                original_address.display_address if original_address is not None else None
            ),
            geocoded_address=geocoded_address.display_address if geocoded_address else None,
            legal_dong_code_before=before,
            legal_dong_code_after=after,
            match_level=match_level,
            confidence=confidence,
            code_source=code_source,
            provider_code_type=provider_code_type,
            provider_code_value=provider_code_value,
            notes=tuple(notes),
        ),
    )


def coerce_address(
    address: Address | Mapping[str, Any] | None,
    raw: Mapping[str, Any] | None = None,
) -> Address | None:
    if isinstance(address, Address):
        return address
    if isinstance(address, Mapping):
        return _address_from_mapping(address) or Address()
    if raw:
        return _address_from_mapping(raw)
    return None


def address_code_set_from_raw(
    raw: Mapping[str, Any],
    *,
    notes: list[str] | None = None,
) -> AddressCodeSet | None:
    try:
        return AddressCodeSet.from_mapping(raw)
    except ValueError as exc:
        if notes is not None:
            notes.append(f"address code normalization skipped: {exc}")
        return None


def address_with_code_set(
    address: Address,
    code_set: AddressCodeSet,
) -> tuple[Address, AddressMatchLevel]:
    code = code_set.legal_dong_code
    level: AddressMatchLevel = "provider_code_converted"
    if code is None and code_set.sigungu_code is not None:
        code = code_set.sigungu_code.legal_dong_code
        level = "sigungu_code_only"
    if code is None:
        return address, "address_text_only" if address.display_address else "no_address"

    mapping = _address_to_mapping(address)
    mapping.update(code_set.to_orm_dict())
    mapping["legal_dong_code"] = code.code
    if code_set.road_name_address_code is not None:
        mapping["road_name_address_code"] = code_set.road_name_address_code.code
    if code_set.road_name_code is not None:
        mapping["road_name_code"] = code_set.road_name_code.code
    if code_set.building_management_number is not None:
        mapping["building_management_number"] = code_set.building_management_number
    return Address.from_mapping(mapping) or address, level


def merge_address_enrichment(base: Address, enrichment: Address) -> Address:
    """Keep provider display text and overlay geocoded address codes."""

    base_mapping = _address_to_mapping(base)
    enrichment_mapping = _address_to_mapping(enrichment)
    merged = {**enrichment_mapping, **base_mapping}
    if enrichment.legal_dong_code:
        merged["legal_dong_code"] = enrichment.legal_dong_code
    if enrichment.sigungu_code:
        merged["sigungu_code"] = enrichment.sigungu_code
    road_code = _road_name_code(enrichment)
    if road_code:
        merged["road_name_code"] = road_code
    road_address_code = _road_name_address_code(enrichment)
    if road_address_code:
        merged["road_name_address_code"] = road_address_code
    if "address" not in merged and enrichment.display_address:
        merged["address"] = enrichment.display_address
    try:
        return Address.from_mapping(merged) or base
    except ValueError:
        return Address(
            address=base.address or enrichment.address,
            region=_merged_region(base, enrichment),
            jibun=base.jibun or enrichment.jibun,
            road_name=base.road_name or enrichment.road_name,
            postal_code=base.postal_code or enrichment.postal_code,
            detail_address=base.detail_address or enrichment.detail_address,
        )


def provider_address_code(raw: Mapping[str, Any]) -> tuple[str | None, str | None]:
    for key in (
        "sigun_code",
        "SIGUNCD",
        "area_code",
        "areacode",
        "sigungucode",
        "l_dong_regn_cd",
        "lDongRegnCd",
        "l_dong_signgu_cd",
        "lDongSignguCd",
    ):
        value = raw.get(key)
        if value not in (None, ""):
            return key, str(value)
    return None, None


def _call_reverse_geocoder(
    coordinate: PlaceCoordinate | None,
    reverse_geocoder: ReverseGeocoder | None,
    *,
    notes: list[str],
) -> Address | None:
    if coordinate is None or reverse_geocoder is None:
        return None
    result = reverse_geocoder(coordinate)
    address = _address_from_geocoder_result(result)
    if result is not None and address is None:
        notes.append("reverse geocoder returned no address DTO-compatible value")
    return address


def _call_address_geocoder(
    address: Address,
    coordinate: PlaceCoordinate | None,
    address_geocoder: AddressGeocoder | None,
    *,
    notes: list[str],
) -> tuple[PlaceCoordinate | None, Address | None]:
    if coordinate is not None or address_geocoder is None or not address.display_address:
        return None, None
    result = address_geocoder(address)
    coordinate_result = _coordinate_from_geocoder_result(result)
    address_result = _address_from_geocoder_result(result)
    if result is not None and coordinate_result is None:
        notes.append("address geocoder returned no coordinate DTO-compatible value")
    return coordinate_result, address_result


def _address_from_geocoder_result(result: Any) -> Address | None:
    if result is None:
        return None
    if isinstance(result, Address):
        return result
    address = getattr(result, "address", None)
    if isinstance(address, Address):
        return address
    if isinstance(address, Mapping):
        return _address_from_mapping(address)
    if isinstance(result, Mapping):
        return _address_from_mapping(result)
    if hasattr(result, "model_dump"):
        dumped = result.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return _address_from_mapping(dumped)
    mapping = _geocoder_attr_mapping(result)
    if mapping:
        return _address_from_mapping(mapping)
    return None


def _coordinate_from_geocoder_result(result: Any) -> PlaceCoordinate | None:
    if result is None:
        return None
    if isinstance(result, PlaceCoordinate):
        return result
    coordinate = getattr(result, "coordinate", None) or getattr(result, "coord", None)
    if isinstance(coordinate, PlaceCoordinate):
        return coordinate
    if isinstance(coordinate, Mapping):
        return _coordinate_from_mapping(coordinate)
    if isinstance(result, Mapping):
        return _coordinate_from_mapping(result)
    if hasattr(result, "model_dump"):
        dumped = result.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return _coordinate_from_mapping(dumped)
    mapping: dict[str, Any] = {}
    for attr in ("lat", "latitude", "lon", "longitude", "x", "y", "crs"):
        value = getattr(result, attr, None)
        if value not in (None, ""):
            mapping[attr] = value
    return _coordinate_from_mapping(mapping)


def _coordinate_from_mapping(row: Mapping[str, Any]) -> PlaceCoordinate | None:
    lat = row.get("lat", row.get("latitude"))
    lon = row.get("lon", row.get("longitude"))
    if lat is None or lon is None:
        crs = str(row.get("crs") or "EPSG:4326").upper()
        if crs != "EPSG:4326":
            return None
        lon = row.get("x")
        lat = row.get("y")
    if lat in (None, "") or lon in (None, ""):
        return None
    try:
        return PlaceCoordinate(lat=float(lat), lon=float(lon))
    except (TypeError, ValueError):
        return None


def _resource_value(resource: Any, key: str) -> Any:
    if resource is None:
        return None
    if isinstance(resource, Mapping):
        return resource.get(key)
    return getattr(resource, key, None)


def _resource_bool(resource: Any, key: str, *, default: bool) -> bool:
    value = _resource_value(resource, key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _resource_float(resource: Any, key: str, *, default: float | None) -> float | None:
    value = _resource_value(resource, key)
    if value in (None, ""):
        return default
    return float(value)


def _coordinate_lat(coordinate: PlaceCoordinate) -> float:
    return float(coordinate.lat)


def _coordinate_lon(coordinate: PlaceCoordinate) -> float:
    return float(coordinate.lon)


def _geocoder_attr_mapping(result: Any) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for attr in (
        "postal_code",
        "legal_dong_code",
        "sigungu_code",
        "road_name_code",
        "road_name_address_code",
        "building_management_number",
    ):
        value = getattr(result, attr, None)
        if value not in (None, ""):
            mapping[attr] = value

    road_address = getattr(result, "road_address", None)
    if road_address not in (None, ""):
        mapping["road_address"] = road_address
        mapping.setdefault("address", road_address)

    parcel_address = getattr(result, "parcel_address", None)
    if parcel_address not in (None, ""):
        mapping["jibun_address"] = parcel_address
        mapping.setdefault("address", parcel_address)

    formatted_address = getattr(result, "formatted_address", None)
    if formatted_address not in (None, ""):
        mapping.setdefault("address", formatted_address)

    return mapping


def _address_from_mapping(row: Mapping[str, Any]) -> Address | None:
    try:
        return Address.from_mapping(row)
    except ValueError:
        return None


def _address_to_mapping(address: Address) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    if address.address:
        mapping["address"] = address.address
    elif address.display_address:
        mapping["address"] = address.display_address
    if address.postal_code:
        mapping["postal_code"] = address.postal_code
    if address.detail_address:
        mapping["detail_address"] = address.detail_address
    region = address.effective_region
    if region is not None:
        if region.legal_dong_code_value:
            mapping["legal_dong_code"] = region.legal_dong_code_value
        if region.sigungu_code_value:
            mapping["sigungu_code"] = region.sigungu_code_value
        if region.sido_name:
            mapping["sido_name"] = region.sido_name
        if region.sigungu_name:
            mapping["sigungu_name"] = region.sigungu_name
        if region.eup_myeon_dong_name:
            mapping["eup_myeon_dong_name"] = region.eup_myeon_dong_name
        if region.ri_name:
            mapping["ri_name"] = region.ri_name
    if address.jibun is not None:
        if address.jibun.address:
            mapping["jibun_address"] = address.jibun.address
        if address.jibun.postal_code and "postal_code" not in mapping:
            mapping["postal_code"] = address.jibun.postal_code
    if address.road_name is not None:
        road_name = address.road_name
        if road_name.address:
            mapping["road_address"] = road_name.address
        if road_name.road_name:
            mapping["road_name"] = road_name.road_name
        if road_name.road_name_address_code is not None:
            mapping["road_name_address_code"] = road_name.road_name_address_code.code
        if road_name.effective_road_name_code is not None:
            mapping["road_name_code"] = road_name.effective_road_name_code.code
        if road_name.building_management_number:
            mapping["building_management_number"] = road_name.building_management_number
        if road_name.postal_code and "postal_code" not in mapping:
            mapping["postal_code"] = road_name.postal_code
    return mapping


def _merged_region(base: Address, enrichment: Address) -> AddressRegion | None:
    if enrichment.legal_dong_code:
        return AddressRegion.from_legal_dong_code(enrichment.legal_dong_code)
    return base.effective_region or enrichment.effective_region


def _road_name_code(address: Address) -> str | None:
    road_name = address.road_name
    if not isinstance(road_name, RoadNameAddress):
        return None
    code = road_name.effective_road_name_code
    return code.code if code else None


def _road_name_address_code(address: Address) -> str | None:
    road_name = address.road_name
    if not isinstance(road_name, RoadNameAddress) or road_name.road_name_address_code is None:
        return None
    return road_name.road_name_address_code.code


def _same_address_text(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return _compact_address(left) == _compact_address(right)


def _compact_address(value: str) -> str:
    return "".join(value.casefold().split())
