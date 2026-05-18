from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from kraddr.base import (
    Address,
    AddressCodeSet,
    AddressRegion,
    PlaceCoordinate,
    RoadNameAddress,
)

AddressMatchLevel: TypeAlias = Literal[
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


def enrich_address_from_coordinate(
    *,
    address: Address | Mapping[str, Any] | None = None,
    coordinate: PlaceCoordinate | None = None,
    raw: Mapping[str, Any] | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
    source_label: str,
    source_entity_id: str | None = None,
) -> AddressEnrichment:
    """Normalize an address and optionally enrich it from a coordinate.

    `python-krtour-map` does not wrap a geocoding provider. TripMate can inject a
    stable reverse-geocoding callable backed by `python-kraddr-geo`,
    `python-vworld-api`, or another provider public client.
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
    return None


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
