"""``krtour.map.providers.tripmate_agent`` — TripMate-agent YouTube 후보 → FeatureBundle.

``tripmate-agent``는 YouTube 여행 콘텐츠에서 장소 후보와 근거를 추출하고,
``python-krtour-map``은 문서화된 ``/api/v1/krtour/features/*`` JSON을 pull해
최종 ``Feature``/``SourceRecord``/``SourceLink``로 소유한다. 이 모듈은 REST client
wrapper가 아니라, 이미 받은 export item dict를 DTO로 바꾸는 순수 변환 함수다.

ADR 참조: ADR-006 / ADR-009 / ADR-019 / ADR-024 / ADR-045
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from krtour.map.category import PlaceCategoryCode, mapbox_maki_icon_or_none
from krtour.map.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_korean_text,
)
from krtour.map.core.ids import make_feature_id, make_payload_hash, make_source_record_key
from krtour.map.core.providers import normalize_provider_name
from krtour.map.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    RawDataRef,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from krtour.map.geocoding import ReverseGeocoder, cached_reverse_geocoder

__all__ = [
    "DATASET_KEY_YOUTUBE_PLACE_CANDIDATES",
    "TRIPMATE_AGENT_MARKER_COLOR",
    "TRIPMATE_AGENT_PROVIDER_NAME",
    "TRIPMATE_AGENT_YOUTUBE_CATEGORY_FALLBACK",
    "TripmateAgentFeatureItem",
    "tripmate_agent_items_to_bundles",
]


TripmateAgentFeatureItem = Mapping[str, Any]
"""TripMate-agent ``/api/v1/krtour/features/*`` item JSON shape."""

TRIPMATE_AGENT_PROVIDER_NAME: Final[str] = "tripmate-agent-youtube"
"""YouTube 장소 후보 provider canonical name."""

DATASET_KEY_YOUTUBE_PLACE_CANDIDATES: Final[str] = "youtube_place_candidates"
"""TripMate-agent export dataset key."""

_SOURCE_ENTITY_TYPE: Final[str] = "extracted_place_candidate"
_PLACE_KIND: Final[str] = "youtube_place_candidate"
TRIPMATE_AGENT_YOUTUBE_CATEGORY_FALLBACK: Final[str] = PlaceCategoryCode.TOURISM.value
"""TripMate-agent category suggestion이 없거나 잘못된 경우의 안전한 fallback."""

TRIPMATE_AGENT_MARKER_COLOR: Final[str] = "P-13"
_DEFAULT_MARKER_ICON: Final[str] = "marker"


async def tripmate_agent_items_to_bundles(
    items: Iterable[TripmateAgentFeatureItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """TripMate-agent feature export items → ``list[FeatureBundle]``.

    ``operation``이 ``upsert``가 아닌 ``reject``/``tombstone`` item은 현재 적재형
    ``FeatureBundle``로 표현할 수 없으므로 건너뛴다. 실제 삭제/거절 cursor 처리는
    export ledger가 붙는 후속 작업에서 별도 상태 전이로 다룬다.
    """
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    bundles: list[FeatureBundle] = []
    for item in items:
        if _operation(item) != "upsert":
            continue
        bundle = await _item_to_bundle(
            item,
            fetched_at=fetched_at,
            reverse_geocoder=geocoder,
        )
        if bundle is not None:
            bundles.append(bundle)
    return bundles


async def _item_to_bundle(
    item: TripmateAgentFeatureItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
) -> FeatureBundle | None:
    place = _mapping(item.get("place"))
    source_record_payload = _mapping(item.get("source_record"))
    name = normalize_korean_text(_text(place, "name"))
    source_entity_id = _source_entity_id(item, source_record_payload)
    if not name or not source_entity_id:
        return None

    provider = normalize_provider_name(
        _text(source_record_payload, "provider") or TRIPMATE_AGENT_PROVIDER_NAME
    )
    dataset_key = (
        _text(source_record_payload, "dataset_key")
        or DATASET_KEY_YOUTUBE_PLACE_CANDIDATES
    )
    source_entity_type = (
        _text(source_record_payload, "source_entity_type") or _SOURCE_ENTITY_TYPE
    )
    category = _category(place)
    coord = _coordinate(place)

    address_payload = _mapping(place.get("address"))
    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    address = _address(address_payload, geo=geo)
    bjd_code = address.bjd_code

    raw_data = _plain_json_dict(item)
    payload_hash = (
        _text(source_record_payload, "raw_payload_hash") or make_payload_hash(raw_data)
    )
    source_record_key = make_source_record_key(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.PLACE.value,
        category=category,
        source_type=f"{provider}:{dataset_key}",
        source_natural_key=source_entity_id,
    )

    youtube = _mapping(item.get("youtube"))
    evidence = _mapping(item.get("evidence"))
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=name,
        coord=coord,
        address=address,
        category=category,
        marker_icon=mapbox_maki_icon_or_none(category) or _DEFAULT_MARKER_ICON,
        marker_color=TRIPMATE_AGENT_MARKER_COLOR,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=_PLACE_KIND,
            facility_info=_facility_info(place, youtube, evidence),
            payload={
                "tripmate_agent": {
                    "export_id": item.get("export_id"),
                    "operation": _operation(item),
                    "youtube": _plain_json_value(youtube),
                    "evidence": _plain_json_value(evidence),
                    "updated_at": item.get("updated_at"),
                }
            },
        ),
        raw_refs=[
            RawDataRef(
                provider=provider,
                dataset_key=dataset_key,
                source_entity_id=source_entity_id,
                source_role=SourceRole.PRIMARY,
                fetched_at=fetched_at,
                payload_hash=payload_hash,
                extra={"export_id": item.get("export_id")},
            )
        ],
    )
    source_record = SourceRecord(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
        source_version=None,
        raw_name=name,
        raw_address=address.display() or None,
        raw_longitude=coord.lon if coord is not None else None,
        raw_latitude=coord.lat if coord is not None else None,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="tripmate_agent_export",
        confidence=_confidence(evidence.get("confidence_score")),
        is_primary_source=True,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )


def _operation(item: Mapping[str, Any]) -> str:
    return str(item.get("operation") or "upsert").strip().lower()


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _source_entity_id(
    item: Mapping[str, Any], source_record_payload: Mapping[str, Any]
) -> str | None:
    for value in (
        source_record_payload.get("source_entity_id"),
        item.get("candidate_id"),
        item.get("export_id"),
    ):
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _category(place: Mapping[str, Any]) -> str:
    value = _text(place, "category_code_suggestion")
    if value is not None and len(value) == 8 and value.isdigit():
        return value
    return TRIPMATE_AGENT_YOUTUBE_CATEGORY_FALLBACK


def _coordinate(place: Mapping[str, Any]) -> Coordinate | None:
    lon = _decimal_or_none(place.get("longitude"))
    lat = _decimal_or_none(place.get("latitude"))
    if lon is None or lat is None:
        return None
    return Coordinate(lon=lon, lat=lat)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _address(payload: Mapping[str, Any], *, geo: Address | None) -> Address:
    bjd_code = _ten_digit_code(_text(payload, "legal_dong_code"))
    if bjd_code is None and geo is not None:
        bjd_code = geo.bjd_code
    sigungu_code = (
        _five_digit_code(_text(payload, "sigungu_code"))
        or (geo.sigungu_code if geo is not None else None)
        or extract_sigungu_code(bjd_code)
    )
    sido_code = (
        _two_digit_code(_text(payload, "sido_code"))
        or (geo.sido_code if geo is not None else None)
        or extract_sido_code(bjd_code)
    )
    return Address(
        road=normalize_korean_text(_text(payload, "road_address")),
        legal=normalize_korean_text(_text(payload, "official_address")),
        admin=geo.admin if geo is not None else None,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        road_name_code=geo.road_name_code if geo is not None else None,
        zipcode=geo.zipcode if geo is not None else None,
        sido_name=geo.sido_name if geo is not None else None,
        sigungu_name=geo.sigungu_name if geo is not None else None,
    )


def _ten_digit_code(value: str | None) -> str | None:
    return value if value is not None and len(value) == 10 and value.isdigit() else None


def _five_digit_code(value: str | None) -> str | None:
    return value if value is not None and len(value) == 5 and value.isdigit() else None


def _two_digit_code(value: str | None) -> str | None:
    return value if value is not None and len(value) == 2 and value.isdigit() else None


def _facility_info(
    place: Mapping[str, Any],
    youtube: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    values = {
        "description": _text(place, "description"),
        "gemini_enriched_description": _text(place, "gemini_enriched_description"),
        "category_label": _text(place, "category_label"),
        "youtube_video_id": _text(youtube, "video_id"),
        "youtube_video_url": _text(youtube, "video_url"),
        "youtube_video_title": _text(youtube, "video_title"),
        "youtube_channel_id": _text(youtube, "channel_id"),
        "youtube_channel_title": _text(youtube, "channel_title"),
        "youtube_playlist_id": _text(youtube, "playlist_id"),
        "youtube_playlist_title": _text(youtube, "playlist_title"),
        "timestamp_start": _text(evidence, "timestamp_start"),
        "timestamp_end": _text(evidence, "timestamp_end"),
        "transcript_excerpt": _text(evidence, "transcript_excerpt"),
        "gemini_url_evidence": _text(evidence, "gemini_url_evidence"),
    }
    return {key: value for key, value in values.items() if value is not None}


def _confidence(value: Any) -> int:
    if value is None:
        return 80
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 80
    if 0 <= score <= 1:
        score *= 100
    return max(0, min(100, round(score)))


def _plain_json_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): _plain_json_value(item)
        for key, item in value.items()
        if isinstance(key, str)
    }


def _plain_json_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return _plain_json_dict(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_plain_json_value(item) for item in value]
    return str(value)
