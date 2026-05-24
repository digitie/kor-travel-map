from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from html import unescape
from typing import Any, Literal, Protocol, TypeAlias
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from krtour_map.enums import FeatureKind, SourceRole
from krtour_map.ids import make_payload_hash
from krtour_map.models import Coordinate, Feature, PlaceDetail, SourceLink, SourceRecord

KAKAO_LOCAL_PROVIDER = "kakao-local-api"
NAVER_SEARCH_PROVIDER = "naver-search-api"
GOOGLE_PLACES_PROVIDER = "google-places-api-new"
PLACE_PHONE_ENRICHMENT_DATASET_KEY = "place_phone_enrichment"
PLACE_PHONE_ENRICHMENT_VERSION = "place-phone-enrichment-v1"
GOOGLE_PLACES_PHONE_FIELD_MASK = ",".join(
    (
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.googleMapsUri",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
    )
)

HttpMethod: TypeAlias = Literal["GET", "POST"]
JsonMapping: TypeAlias = Mapping[str, Any]


class PlaceSearchError(RuntimeError):
    """Base error for optional place-search phone enrichment."""


class PlaceSearchHttpError(PlaceSearchError):
    """Raised when a place-search provider returns an HTTP or network error."""


@dataclass(frozen=True)
class PlaceHttpRequest:
    method: HttpMethod
    url: str
    headers: Mapping[str, str]
    params: Mapping[str, Any] | None = None
    json_body: Mapping[str, Any] | None = None
    timeout_seconds: float = 5.0


PlaceHttpTransport: TypeAlias = Callable[[PlaceHttpRequest], JsonMapping]


@dataclass(frozen=True)
class PlaceSearchCandidate:
    provider: str
    provider_place_id: str
    name: str
    phone: str | None = None
    address_name: str | None = None
    road_address_name: str | None = None
    coord: Coordinate | None = None
    place_url: str | None = None
    category: str | None = None
    raw: Mapping[str, Any] | None = None
    confidence: int = 0
    match_method: str = "place_search"


class PlacePhoneSearcher(Protocol):
    def __call__(self, feature: Feature) -> Iterable[PlaceSearchCandidate]: ...


@dataclass(frozen=True)
class PlacePhoneEnrichmentResult:
    feature: Feature
    place_detail: PlaceDetail
    candidates: tuple[PlaceSearchCandidate, ...] = ()
    added_phones: tuple[str, ...] = ()
    source_records: tuple[SourceRecord, ...] = ()
    source_links: tuple[SourceLink, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(repr=False)
class KakaoLocalPlaceSearcher:
    """Kakao Local keyword searcher for feature phone enrichment."""

    rest_api_key: str
    endpoint: str = "https://dapi.kakao.com/v2/local/search/keyword.json"
    size: int = 5
    radius_m: int = 5000
    timeout_seconds: float = 5.0
    transport: PlaceHttpTransport | None = None

    def __call__(self, feature: Feature) -> tuple[PlaceSearchCandidate, ...]:
        query = place_search_query(feature)
        if not query:
            return ()
        params: dict[str, Any] = {
            "query": query,
            "size": max(1, min(self.size, 15)),
            "sort": "accuracy",
        }
        if feature.coord is not None:
            params.update(
                {
                    "x": feature.coord.longitude,
                    "y": feature.coord.latitude,
                    "radius": max(0, min(self.radius_m, 20000)),
                }
            )
        payload = self._transport()(
            PlaceHttpRequest(
                method="GET",
                url=self.endpoint,
                headers={"Authorization": f"KakaoAK {self.rest_api_key}"},
                params=params,
                timeout_seconds=self.timeout_seconds,
            )
        )
        documents = payload.get("documents") or ()
        candidates = [
            _score_candidate(feature, _kakao_candidate(document))
            for document in documents
            if isinstance(document, Mapping)
        ]
        return tuple(candidates)

    def _transport(self) -> PlaceHttpTransport:
        return self.transport or default_place_http_transport


@dataclass(repr=False)
class NaverLocalPlaceSearcher:
    """Naver Search local searcher.

    Naver's official local-search `telephone` field is currently retained only for
    backward compatibility and normally returns an empty value. This searcher still
    normalizes a phone if the API ever returns one.
    """

    client_id: str
    client_secret: str
    endpoint: str = "https://openapi.naver.com/v1/search/local.json"
    display: int = 5
    timeout_seconds: float = 5.0
    transport: PlaceHttpTransport | None = None

    def __call__(self, feature: Feature) -> tuple[PlaceSearchCandidate, ...]:
        query = place_search_query(feature)
        if not query:
            return ()
        payload = self._transport()(
            PlaceHttpRequest(
                method="GET",
                url=self.endpoint,
                headers={
                    "X-Naver-Client-Id": self.client_id,
                    "X-Naver-Client-Secret": self.client_secret,
                },
                params={
                    "query": query,
                    "display": max(1, min(self.display, 5)),
                    "start": 1,
                    "sort": "random",
                },
                timeout_seconds=self.timeout_seconds,
            )
        )
        items = payload.get("items") or ()
        candidates = [
            _score_candidate(feature, _naver_candidate(item))
            for item in items
            if isinstance(item, Mapping)
        ]
        return tuple(candidates)

    def _transport(self) -> PlaceHttpTransport:
        return self.transport or default_place_http_transport


@dataclass(repr=False)
class GooglePlacesTextSearcher:
    """Google Places API Text Search (New) searcher for phone enrichment."""

    api_key: str
    endpoint: str = "https://places.googleapis.com/v1/places:searchText"
    field_mask: str = GOOGLE_PLACES_PHONE_FIELD_MASK
    max_result_count: int = 5
    radius_m: int = 5000
    timeout_seconds: float = 5.0
    transport: PlaceHttpTransport | None = None

    def __call__(self, feature: Feature) -> tuple[PlaceSearchCandidate, ...]:
        query = place_search_query(feature)
        if not query:
            return ()
        body: dict[str, Any] = {
            "textQuery": query,
            "languageCode": "ko",
            "regionCode": "KR",
            "maxResultCount": max(1, min(self.max_result_count, 20)),
        }
        if feature.coord is not None:
            body["locationBias"] = {
                "circle": {
                    "center": {
                        "latitude": feature.coord.latitude,
                        "longitude": feature.coord.longitude,
                    },
                    "radius": max(1, self.radius_m),
                }
            }
        payload = self._transport()(
            PlaceHttpRequest(
                method="POST",
                url=self.endpoint,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": self.api_key,
                    "X-Goog-FieldMask": self.field_mask,
                },
                json_body=body,
                timeout_seconds=self.timeout_seconds,
            )
        )
        places = payload.get("places") or ()
        candidates = [
            _score_candidate(feature, _google_candidate(place))
            for place in places
            if isinstance(place, Mapping)
        ]
        return tuple(candidates)

    def _transport(self) -> PlaceHttpTransport:
        return self.transport or default_place_http_transport


def default_place_http_transport(request: PlaceHttpRequest) -> JsonMapping:
    url = request.url
    if request.params:
        query = urlencode(
            {key: value for key, value in request.params.items() if value is not None}
        )
        url = f"{url}?{query}"

    data = None
    headers = dict(request.headers)
    if request.json_body is not None:
        data = json.dumps(request.json_body, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    http_request = Request(url, data=data, headers=headers, method=request.method)
    try:
        with urlopen(http_request, timeout=request.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        message = f"{request.method} {request.url} failed: {exc.code} {body}"
        raise PlaceSearchHttpError(message) from exc
    except URLError as exc:
        raise PlaceSearchHttpError(f"{request.method} {request.url} failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise PlaceSearchHttpError(f"{request.method} {request.url} returned invalid JSON") from exc


def place_search_query(feature: Feature) -> str:
    parts = [feature.name]
    address_text = feature.address.display_address
    if address_text:
        parts.append(address_text)
    return " ".join(part.strip() for part in parts if part and part.strip())


def place_phone_searchers_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    transport: PlaceHttpTransport | None = None,
) -> tuple[PlacePhoneSearcher, ...]:
    env = environ or os.environ
    searchers: list[PlacePhoneSearcher] = []

    kakao_key = env.get("KAKAO_REST_API_KEY") or env.get("KAKAO_LOCAL_REST_API_KEY")
    if kakao_key:
        searchers.append(KakaoLocalPlaceSearcher(kakao_key, transport=transport))

    naver_id = env.get("NAVER_CLIENT_ID") or env.get("NAVER_SEARCH_CLIENT_ID")
    naver_secret = env.get("NAVER_CLIENT_SECRET") or env.get("NAVER_SEARCH_CLIENT_SECRET")
    if naver_id and naver_secret:
        searchers.append(NaverLocalPlaceSearcher(naver_id, naver_secret, transport=transport))

    google_key = env.get("GOOGLE_PLACES_API_KEY") or env.get("GOOGLE_MAPS_API_KEY")
    if google_key:
        searchers.append(GooglePlacesTextSearcher(google_key, transport=transport))

    return tuple(searchers)


def resolve_place_phone_searchers(resource: Any) -> tuple[PlacePhoneSearcher, ...]:
    direct = _resource_value(resource, "place_phone_searchers")
    if direct is not None:
        return _coerce_searchers(direct)

    direct = _resource_value(resource, "place_searchers")
    if direct is not None:
        return _coerce_searchers(direct)

    environ = _resource_value(resource, "place_enrichment_env")
    transport = _resource_value(resource, "place_http_transport")
    if environ is not None:
        if not isinstance(environ, Mapping):
            raise TypeError("place_enrichment_env must be a mapping")
        if transport is not None and not callable(transport):
            raise TypeError("place_http_transport must be callable")
        return place_phone_searchers_from_env(environ, transport=transport)

    kakao_key = _resource_value(resource, "kakao_rest_api_key")
    naver_id = _resource_value(resource, "naver_client_id")
    naver_secret = _resource_value(resource, "naver_client_secret")
    google_key = _resource_value(resource, "google_places_api_key")
    if not any((kakao_key, naver_id and naver_secret, google_key)):
        return ()

    if transport is not None and not callable(transport):
        raise TypeError("place_http_transport must be callable")

    searchers: list[PlacePhoneSearcher] = []
    if kakao_key:
        searchers.append(KakaoLocalPlaceSearcher(str(kakao_key), transport=transport))
    if naver_id and naver_secret:
        searchers.append(
            NaverLocalPlaceSearcher(str(naver_id), str(naver_secret), transport=transport)
        )
    if google_key:
        searchers.append(GooglePlacesTextSearcher(str(google_key), transport=transport))
    return tuple(searchers)


def enrich_place_phone(
    feature: Feature,
    place_detail: PlaceDetail | None = None,
    *,
    searchers: Iterable[PlacePhoneSearcher] = (),
    max_phones: int = 3,
    min_confidence: int = 60,
    ignore_errors: bool = True,
) -> PlacePhoneEnrichmentResult:
    if str(feature.kind) != FeatureKind.PLACE.value:
        detail = place_detail or PlaceDetail(feature_id=feature.feature_id)
        return PlacePhoneEnrichmentResult(feature=feature, place_detail=detail)

    detail = place_detail or PlaceDetail(feature_id=feature.feature_id)
    existing_phones = list(detail.phones)
    existing_phone_keys = {_phone_key(phone) for phone in existing_phones if _phone_key(phone)}
    candidate_rows: list[PlaceSearchCandidate] = []
    errors: list[str] = []

    for searcher in tuple(searchers):
        try:
            candidate_rows.extend(searcher(feature))
        except Exception as exc:  # noqa: BLE001 - optional enrichment must not break ETL by default.
            if not ignore_errors:
                raise
            errors.append(str(exc))

    selected: list[PlaceSearchCandidate] = []
    added_phones: list[str] = []
    for candidate in sorted(candidate_rows, key=lambda row: row.confidence, reverse=True):
        phone = _clean_phone(candidate.phone)
        phone_key = _phone_key(phone)
        if not phone or not phone_key or phone_key in existing_phone_keys:
            continue
        if candidate.confidence < min_confidence:
            continue
        selected.append(candidate)
        added_phones.append(phone)
        existing_phone_keys.add(phone_key)
        if len(existing_phones) + len(added_phones) >= max_phones:
            break

    if not added_phones:
        return PlacePhoneEnrichmentResult(
            feature=feature,
            place_detail=detail,
            candidates=tuple(candidate_rows),
            errors=tuple(errors),
        )

    payload = dict(detail.payload)
    payload["place_phone_enrichment"] = {
        "version": PLACE_PHONE_ENRICHMENT_VERSION,
        "added_phones": added_phones,
        "candidates": [_candidate_payload(candidate, include_raw=False) for candidate in selected],
        "errors": errors,
    }
    enriched_detail = detail.model_copy(
        update={
            "phones": [*existing_phones, *added_phones][:max_phones],
            "payload": payload,
        }
    )
    source_records = tuple(_candidate_source_record(candidate) for candidate in selected)
    source_links = tuple(
        SourceLink(
            feature_id=feature.feature_id,
            source_record_key=source_record.key(),
            source_role=SourceRole.ENRICHMENT,
            match_method=candidate.match_method,
            confidence=candidate.confidence,
            is_primary_source=False,
        )
        for candidate, source_record in zip(selected, source_records, strict=True)
    )
    return PlacePhoneEnrichmentResult(
        feature=feature,
        place_detail=enriched_detail,
        candidates=tuple(candidate_rows),
        added_phones=tuple(added_phones),
        source_records=source_records,
        source_links=source_links,
        errors=tuple(errors),
    )


def _kakao_candidate(document: Mapping[str, Any]) -> PlaceSearchCandidate:
    return PlaceSearchCandidate(
        provider=KAKAO_LOCAL_PROVIDER,
        provider_place_id=str(document.get("id") or _stable_candidate_id(document)),
        name=_text(document.get("place_name")) or "",
        phone=_text(document.get("phone")),
        address_name=_text(document.get("address_name")),
        road_address_name=_text(document.get("road_address_name")),
        coord=_coordinate(document.get("y"), document.get("x")),
        place_url=_text(document.get("place_url")),
        category=_text(document.get("category_name")),
        raw=dict(document),
        match_method="kakao_keyword_phone",
    )


def _naver_candidate(item: Mapping[str, Any]) -> PlaceSearchCandidate:
    return PlaceSearchCandidate(
        provider=NAVER_SEARCH_PROVIDER,
        provider_place_id=_text(item.get("link")) or _stable_candidate_id(item),
        name=_strip_html(_text(item.get("title")) or ""),
        phone=_text(item.get("telephone")),
        address_name=_text(item.get("address")),
        road_address_name=_text(item.get("roadAddress")),
        coord=_naver_coordinate(item.get("mapy"), item.get("mapx")),
        place_url=_text(item.get("link")),
        category=_strip_html(_text(item.get("category")) or "") or None,
        raw=dict(item),
        match_method="naver_local_phone",
    )


def _google_candidate(place: Mapping[str, Any]) -> PlaceSearchCandidate:
    display_name = place.get("displayName")
    name = ""
    if isinstance(display_name, Mapping):
        name = _text(display_name.get("text")) or ""
    location = place.get("location")
    coord = None
    if isinstance(location, Mapping):
        coord = _coordinate(location.get("latitude"), location.get("longitude"))
    return PlaceSearchCandidate(
        provider=GOOGLE_PLACES_PROVIDER,
        provider_place_id=str(place.get("id") or place.get("name") or _stable_candidate_id(place)),
        name=name,
        phone=_text(place.get("nationalPhoneNumber"))
        or _text(place.get("internationalPhoneNumber")),
        address_name=_text(place.get("formattedAddress")),
        road_address_name=None,
        coord=coord,
        place_url=_text(place.get("googleMapsUri")),
        category=_text(place.get("primaryType")),
        raw=dict(place),
        match_method="google_text_search_phone",
    )


def _score_candidate(feature: Feature, candidate: PlaceSearchCandidate) -> PlaceSearchCandidate:
    score = 0
    feature_name = _normalize_text(feature.name)
    candidate_name = _normalize_text(candidate.name)
    if feature_name and candidate_name:
        if feature_name == candidate_name:
            score += 50
        elif feature_name in candidate_name or candidate_name in feature_name:
            score += 38
        else:
            score += min(28, int(28 * _token_overlap(feature_name, candidate_name)))

    feature_address = _normalize_text(feature.address.display_address)
    candidate_address = _normalize_text(
        " ".join(
            part
            for part in (candidate.road_address_name, candidate.address_name)
            if part is not None
        )
    )
    if feature_address and candidate_address:
        if feature_address in candidate_address or candidate_address in feature_address:
            score += 20
        else:
            score += min(15, int(15 * _token_overlap(feature_address, candidate_address)))

    if feature.coord is not None and candidate.coord is not None:
        distance_m = _distance_m(feature.coord, candidate.coord)
        if distance_m <= 100:
            score += 20
        elif distance_m <= 500:
            score += 15
        elif distance_m <= 1000:
            score += 10
        elif distance_m <= 3000:
            score += 5

    if _clean_phone(candidate.phone):
        score += 10

    confidence = max(0, min(score, 100))
    return replace(candidate, confidence=confidence)


def _candidate_source_record(candidate: PlaceSearchCandidate) -> SourceRecord:
    raw = dict(candidate.raw or _candidate_payload(candidate, include_raw=False))
    return SourceRecord(
        provider=candidate.provider,
        dataset_key=PLACE_PHONE_ENRICHMENT_DATASET_KEY,
        source_entity_type="place",
        source_entity_id=candidate.provider_place_id,
        raw_name=candidate.name,
        raw_address=candidate.road_address_name or candidate.address_name,
        raw_longitude=(
            Decimal(str(candidate.coord.longitude)) if candidate.coord is not None else None
        ),
        raw_latitude=(
            Decimal(str(candidate.coord.latitude)) if candidate.coord is not None else None
        ),
        raw_data=raw,
        raw_payload_hash=make_payload_hash(raw),
    )


def _candidate_payload(
    candidate: PlaceSearchCandidate,
    *,
    include_raw: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": candidate.provider,
        "provider_place_id": candidate.provider_place_id,
        "name": candidate.name,
        "phone": candidate.phone,
        "address_name": candidate.address_name,
        "road_address_name": candidate.road_address_name,
        "place_url": candidate.place_url,
        "category": candidate.category,
        "confidence": candidate.confidence,
        "match_method": candidate.match_method,
    }
    if candidate.coord is not None:
        payload["coordinate"] = {
            "latitude": candidate.coord.latitude,
            "longitude": candidate.coord.longitude,
        }
    if include_raw:
        payload["raw"] = dict(candidate.raw or {})
    return payload


def _coerce_searchers(value: Any) -> tuple[PlacePhoneSearcher, ...]:
    if callable(value):
        return (value,)
    try:
        searchers = tuple(value)
    except TypeError as exc:
        raise TypeError("place_phone_searchers must be a callable or iterable") from exc
    for searcher in searchers:
        if not callable(searcher):
            raise TypeError("place_phone_searchers must contain only callables")
    return searchers


def _resource_value(resource: Any, key: str) -> Any:
    if resource is None:
        return None
    if isinstance(resource, Mapping):
        return resource.get(key)
    return getattr(resource, key, None)


def _stable_candidate_id(value: Mapping[str, Any]) -> str:
    return make_payload_hash(dict(value), length=20)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_phone(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    return re.sub(r"\s+", "", text)


def _phone_key(value: Any) -> str:
    text = _clean_phone(value)
    if text is None:
        return ""
    return re.sub(r"\D+", "", text)


def _strip_html(value: str) -> str:
    return unescape(re.sub(r"<[^>]*>", "", value)).strip()


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = _strip_html(value).lower()
    return re.sub(r"[\s\W_]+", "", text)


def _token_overlap(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[\s,./()\-]+", value.lower()) if token}


def _coordinate(latitude: Any, longitude: Any) -> Coordinate | None:
    try:
        lat = Decimal(str(latitude))
        lon = Decimal(str(longitude))
    except (InvalidOperation, TypeError, ValueError):
        return None
    try:
        return Coordinate(lat=lat, lon=lon)
    except ValueError:
        return None


def _naver_coordinate(latitude: Any, longitude: Any) -> Coordinate | None:
    try:
        lat = Decimal(str(latitude)) / Decimal("10000000")
        lon = Decimal(str(longitude)) / Decimal("10000000")
    except (InvalidOperation, TypeError, ValueError):
        return None
    try:
        return Coordinate(lat=lat, lon=lon)
    except ValueError:
        return None


def _distance_m(left: Coordinate, right: Coordinate) -> float:
    radius_m = 6_371_000.0
    lat1 = math.radians(float(left.latitude))
    lat2 = math.radians(float(right.latitude))
    delta_lat = math.radians(float(right.latitude - left.latitude))
    delta_lon = math.radians(float(right.longitude - left.longitude))
    a = (
        math.sin(delta_lat / 2) * math.sin(delta_lat / 2)
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) * math.sin(delta_lon / 2)
    )
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
