"""``kortravelmap.providers.kor_travel_transport`` — kor-travel-transport export 계약 (ADR-106).

Map은 OpiNet 주유소·유가, 한국도로공사(KREX) 휴게소·휴게소 유가·고속도로 돌발,
공항 메타데이터를 provider 라이브러리로 직접 받지 않는다. kor-travel-transport가 수집·저장한 값을
``GET /v1/service/exports/*``(transport ADR-013)로 읽는다. 이 모듈은 그 계약의 Map 쪽 정본이다.

- **provider 정체성**: 모든 dataset의 provider는 ``kor-travel-transport``
  (``source_kind=internal``)다. 자연키는 원천의 것을 그대로 쓴다(주유소 uni_id,
  휴게소 ``name::route::direction``, 휴게소 코드, 돌발 사건 단서, IATA 코드) — ADR-098
  identity ``(dataset, kind, natural_key)``의 세 번째 성분이다.
- **이 모듈은 REST client wrapper가 아니다**(ADR-006은 공개 provider client에 대한 규칙이다).
  HTTP는 Dagster fetcher가 한다. 여기서는 이미 받은 JSON을 **엄격히** 검사해 변환 함수
  (``providers.opinet``/``providers.krex``/``providers.krairport``)가 받는 입력 shape로 바꾼다.
  계약이 어긋나면 :class:`TransportExportContractError`로 실패한다 — 조용히 건너뛰면 적재가
  "성공"으로 기록되고 누락이 숨는다.
- Map은 transport export의 **소비자**다. 계약을 pin·vendoring하지 않는다 — Map에 필드·모양이
  필요하면 transport API를 그에 맞게 바꾼다(같은 PR 쌍, 호환 층 없음). 어긋남은 이 모듈의
  엄격한 런타임 검증이 ``failure_kind``와 함께 run을 실패시켜 드러낸다. 파서 테스트는 Map 소유
  대표 응답(``tests/unit/golden/kor-travel-transport/*.json``)을 쓴다.
- **신선도는 두 겹으로 지킨다.** transport는 근거 수집의 이력이 없거나 실패했거나 stale이면
  503을 낸다(transport ADR-013). Map은 그것만 믿지 않고 200 본문의 ``collection``도 다시
  확인하며(:func:`require_current_collection`), 돌발 집합은 ``collected_at`` 나이까지 잰다
  (:func:`require_fresh_incident_set`). 어긋나면 :class:`TransportExportNotCurrent`로 실패한다 —
  낡거나 빈 집합을 받아들이면 완전 snapshot reconcile이 멀쩡한 feature를 지우거나 사건을 닫는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal

__all__ = [
    "DATASET_KEY_AIRPORTS",
    "DATASET_KEY_FUEL_PRICES",
    "DATASET_KEY_FUEL_STATIONS",
    "DATASET_KEY_HIGHWAY_INCIDENTS",
    "DATASET_KEY_REST_AREAS",
    "DATASET_KEY_REST_AREA_FUEL_PRICES",
    "EXPORT_PATH_AIRPORTS",
    "EXPORT_PATH_FUEL_STATIONS",
    "EXPORT_PATH_FUEL_STATION_PRICE_HISTORY",
    "EXPORT_PATH_HIGHWAY_INCIDENTS_ACTIVE",
    "EXPORT_PATH_REST_AREAS",
    "EXPORT_PATH_REST_AREA_FUEL_PRICES",
    "KOR_TRAVEL_TRANSPORT_PROVIDER_NAME",
    "INCIDENT_SET_MAX_AGE",
    "PriceHistorySourceStatus",
    "SERVICE_TOKEN_HEADER",
    "TransportAirport",
    "TransportCollection",
    "TransportCoordinate",
    "TransportExportContractError",
    "TransportExportEmpty",
    "TransportExportFailure",
    "TransportExportHidden",
    "TransportExportMalformed",
    "TransportExportNotCurrent",
    "TransportExportPage",
    "TransportFuelPrice",
    "TransportFuelPriceHistory",
    "TransportFuelPriceHistoryPoint",
    "TransportFuelStation",
    "TransportHighwayIncident",
    "TransportIncidentActiveSet",
    "TransportRestArea",
    "TransportRestAreaFuelPrice",
    "parse_active_incident_set",
    "parse_airport",
    "parse_airports",
    "parse_collection",
    "parse_export_page",
    "parse_fuel_price_history",
    "parse_fuel_station",
    "parse_rest_area",
    "parse_rest_area_fuel_price",
    "require_current_collection",
    "require_fresh_incident_set",
]

KOR_TRAVEL_TRANSPORT_PROVIDER_NAME: Final[str] = "kor-travel-transport"
"""provider canonical name. transport 저장소·배포 식별자와 같다(transport ADR-010)."""

DATASET_KEY_FUEL_STATIONS: Final[str] = "transport_fuel_stations"
"""오피넷 주유소 place Feature."""
DATASET_KEY_FUEL_PRICES: Final[str] = "transport_fuel_prices"
"""오피넷 주유소 유종별 가격 price Feature + PriceValue."""
DATASET_KEY_REST_AREAS: Final[str] = "transport_rest_areas"
"""고속도로 휴게소 place Feature."""
DATASET_KEY_REST_AREA_FUEL_PRICES: Final[str] = "transport_rest_area_fuel_prices"
"""휴게소 주유소 유가 price Feature + PriceValue."""
DATASET_KEY_HIGHWAY_INCIDENTS: Final[str] = "transport_highway_incidents"
"""고속도로 돌발·통제 notice Feature(활성 집합 reconcile)."""
DATASET_KEY_AIRPORTS: Final[str] = "transport_airports"
"""국내 운영 공항 place Feature."""

SERVICE_TOKEN_HEADER: Final[str] = "X-Kor-Travel-Transport-Service-Token"
"""transport export 토큰 header(transport ADR-013)."""

EXPORT_PATH_FUEL_STATIONS: Final[str] = "/v1/service/exports/fuel-stations"
EXPORT_PATH_REST_AREAS: Final[str] = "/v1/service/exports/rest-areas"
EXPORT_PATH_REST_AREA_FUEL_PRICES: Final[str] = "/v1/service/exports/rest-area-fuel-prices"
EXPORT_PATH_HIGHWAY_INCIDENTS_ACTIVE: Final[str] = "/v1/service/exports/highway-incidents/active"
EXPORT_PATH_AIRPORTS: Final[str] = "/v1/service/exports/airports"
EXPORT_PATH_FUEL_STATION_PRICE_HISTORY: Final[str] = (
    "/v1/service/exports/fuel-stations/{station_key}/price-history"
)
"""주유소 한 곳의 가격 이력(transport T4 — transport ADR-013·``docs/map-service-price-history.md``,
Map ADR-114 결정 4).

Map은 저장하지 않고 요청 시 전한다. ``{station_key}``는 주유소 export의 ``natural_key``(오피넷
uni_id, 선행 0 유지)다(경로 성분으로 escape해 넣는다). 질의는 ``product``·``from``·``to``(timezone이
있는 ISO 시각)·``limit``(한 페이지 전체 행 수, transport 기본 1000·최대 5000)·``cursor``(불투명)다.
휴게소 이력(``/rest-area-fuel-prices/{station_key}/price-history``)은 transport가 저장하지 않아
501이고 Map은 그 경로를 부르지 않는다."""

PriceHistorySourceStatus = Literal["ok", "stale"]
"""200 가격 이력 페이지의 transport ``ServiceExportMeta.source_status``. transport는 ``failed``를
503 problem 본문에만 싣는다 — 200 본문의 ``failed``는 계약 위반이다."""

_PRICE_HISTORY_SOURCE_STATUSES: Final[dict[str, PriceHistorySourceStatus]] = {
    "ok": "ok",
    "stale": "stale",
}


INCIDENT_SET_MAX_AGE: Final[timedelta] = timedelta(minutes=30)
"""돌발 활성 집합의 최대 나이. transport의 503 기준(5분 수집의 6배)과 같은 값이다."""


class TransportExportContractError(ValueError):
    """transport export 응답이 Map이 기대하는 모양과 어긋난다(필수 필드·타입·페이지)."""

    failure_kind: str = "transport_contract"
    retryable: bool = False
    """같은 run의 step 재시도로 풀리지 않는다 — Map이나 transport 코드를 고쳐야 한다."""


class TransportExportFailure(RuntimeError):
    """transport export를 적재 근거로 쓸 수 없다. ``failure_kind``로 원인을 가른다.

    어느 하위 클래스든 **아무것도 적재·삭제·종료하지 않고** run을 실패시킨다. ``retryable``은
    provider lib 예외와 같은 규약이다: 기다리면 풀리는 실패만 ``True``다. Dagster asset 경계는
    ``False``인 것의 step 재시도를 끈다
    (``quota_exhaustion.raise_terminal_if_transport_unrecoverable``).
    """

    failure_kind: str = "transport_unavailable"
    retryable: bool = False


class TransportExportNotCurrent(TransportExportFailure):
    """근거 수집의 이력이 없거나, 실패했거나, stale이다(503이거나 ``collection`` 플래그).

    transport의 다음 수집이 성공하면 풀린다 — **retryable step 실패**다. HTTP 층에서 곧바로 다시
    부르지는 않고(15초 안에 바뀌지 않는다), Dagster ``RetryPolicy``가 step을 다시 돈다.
    """

    failure_kind = "transport_not_current"
    retryable = True


class TransportExportMalformed(TransportExportFailure):
    """본문이 JSON이 아니다(HTML 오류 페이지·잘린 본문 등) — malformed upstream.

    ``json.JSONDecodeError``를 그대로 올리면 분류 없는(unknown) 실패로 남는다.
    """

    failure_kind = "transport_malformed_upstream"


class TransportExportEmpty(TransportExportFailure):
    """완전 snapshot이어야 할 export가 0건이다 — 전량 삭제로 읽지 않는다."""

    failure_kind = "transport_empty"


class TransportExportHidden(TransportExportFailure):
    """transport가 경로를 숨겼다(404): 토큰 불일치, 허용 대역 밖 접속, 또는 export가 없는 버전."""

    failure_kind = "transport_hidden"


# -- 입력 shape ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TransportCoordinate:
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class TransportFuelPrice:
    """주유소 유종 하나의 최신 가격. ``price=None``은 "현재 판매하지 않음"이다."""

    product_code: str
    price: Decimal | None
    provider_updated_at: datetime | None
    """오피넷이 그 유종 가격을 마지막으로 바꾼 시각(``B027_DT`` 등). 가격 자체의 갱신 시각이다."""
    observed_at: datetime
    """transport 원본 행의 관측 시각.

    ``provider_updated_at``이 있으면 그것, 없으면 그 행의 수집 시각이다.
    """
    collected_at: datetime
    """transport가 이 가격을 오피넷 현재가로 **마지막으로 확인한** 수집 시각."""
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TransportFuelStation:
    """오피넷 주유소 1건(``providers.opinet.OpinetStationItem`` 입력 shape)."""

    uni_id: str
    name: str
    brand: str | None
    brand_name: str | None
    address_road: str | None
    address_jibun: str | None
    lon: float | None
    lat: float | None
    tel: str | None
    lpg_yn: bool | None
    is_self: bool | None
    is_24h: bool | None
    has_carwash: bool | None
    has_maintenance: bool | None
    has_cvs: bool | None
    last_seen_at: datetime
    prices: tuple[TransportFuelPrice, ...]
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TransportRestArea:
    """휴게소 1건(``providers.krex.KrexRestAreaItem`` 입력 shape)."""

    natural_key: str
    name: str
    route_name: str | None
    direction: str | None
    lon: float | None
    lat: float | None
    phone_number: str | None
    has_gas_station: bool | None
    has_lpg_station: bool | None
    has_ev_charger: bool | None
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TransportRestAreaFuelPrice:
    """휴게소 주유소 현재 유가(``providers.krex.KrexRestAreaFuelPriceRecord`` 입력 shape)."""

    service_area_code: str
    route_name: str | None
    direction: str | None
    oil_company: str | None
    service_area_name: str | None
    phone_number: str | None
    address: str | None
    gasoline_price: int | None
    diesel_price: int | None
    lpg_price: int | None
    observed_at: datetime
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TransportHighwayIncident:
    """고속도로 돌발 1건(``providers.krex.KrexTrafficNoticeItem`` 입력 shape)."""

    occurred_date: str | None
    occurred_time: str | None
    incident_type: str | None
    incident_type_code: str | None
    direction: str | None
    message: str | None
    point_name: str | None
    route_no: str | None
    route_name: str | None
    process_status: str | None
    process_status_code: str | None
    latitude: float | None
    longitude: float | None
    congestion_length: float | None
    series_no: int | None
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TransportAirport:
    """국내 운영 공항 1건(``providers.krairport.AirportMetadataItem`` 입력 shape)."""

    code: str
    name_korean: str | None
    name_english: str
    icao_code: str | None
    municipality: str | None
    coordinate: TransportCoordinate | None
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TransportCollection:
    """export 근거 수집의 상태(``collection``)."""

    source: str
    last_success_at: datetime | None
    failed: bool
    stale: bool


@dataclass(frozen=True, slots=True)
class TransportExportPage:
    """``{items, next_cursor, has_more, collection}`` 페이지."""

    items: tuple[Mapping[str, Any], ...]
    next_cursor: str | None
    has_more: bool
    collection: TransportCollection


@dataclass(frozen=True, slots=True)
class TransportIncidentActiveSet:
    """마지막 성공 돌발 수집의 활성 사건 전체. 여기 없는 사건은 해소된 것이다."""

    collected_at: datetime
    items: tuple[TransportHighwayIncident, ...]
    collection: TransportCollection


# -- 엄격 파싱 ------------------------------------------------------------------


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TransportExportContractError(f"{where}: JSON object가 아니다.")
    return value


def _required_text(item: Mapping[str, Any], key: str, where: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TransportExportContractError(f"{where}.{key}: 비어 있지 않은 문자열이어야 한다.")
    return value


def _text(item: Mapping[str, Any], key: str, where: str) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TransportExportContractError(f"{where}.{key}: 문자열 또는 null이어야 한다.")
    return value


def _bool(item: Mapping[str, Any], key: str, where: str) -> bool | None:
    value = item.get(key)
    if value is None or isinstance(value, bool):
        return value
    raise TransportExportContractError(f"{where}.{key}: boolean 또는 null이어야 한다.")


def _number(item: Mapping[str, Any], key: str, where: str) -> float | None:
    value = item.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TransportExportContractError(f"{where}.{key}: 숫자 또는 null이어야 한다.")
    return float(value)


def _integer(item: Mapping[str, Any], key: str, where: str) -> int | None:
    value = item.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TransportExportContractError(f"{where}.{key}: 정수 또는 null이어야 한다.")
    return value


def _decimal(item: Mapping[str, Any], key: str, where: str) -> Decimal | None:
    value = item.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise TransportExportContractError(f"{where}.{key}: 숫자 또는 null이어야 한다.")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise TransportExportContractError(f"{where}.{key}: 숫자로 읽을 수 없다.") from exc
    if not parsed.is_finite():
        # NaN·sNaN·Infinity(JSON ``1e400``은 float inf가 된다)는 가격이 아니다 — 받아들이면 응답
        # 직렬화에서 터지거나 잘못된 값이 소비자에게 간다.
        raise TransportExportContractError(f"{where}.{key}: 유한한 숫자여야 한다.")
    return parsed


def _json_number(item: Mapping[str, Any], key: str, where: str) -> Decimal | None:
    """JSON number 또는 null만 받는다(문자열 숫자는 계약 위반). 유한해야 한다."""
    value = item.get(key)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int | float)):
        raise TransportExportContractError(f"{where}.{key}: JSON number 또는 null이어야 한다.")
    return _decimal(item, key, where)


def _datetime(item: Mapping[str, Any], key: str, where: str, *, required: bool) -> datetime | None:
    value = item.get(key)
    if value is None:
        if required:
            raise TransportExportContractError(f"{where}.{key}: 필수 시각이 없다.")
        return None
    if not isinstance(value, str):
        raise TransportExportContractError(f"{where}.{key}: ISO-8601 문자열이어야 한다.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransportExportContractError(f"{where}.{key}: ISO-8601 시각이 아니다.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TransportExportContractError(f"{where}.{key}: timezone이 없는 시각이다.")
    return parsed


def _required_datetime(item: Mapping[str, Any], key: str, where: str) -> datetime:
    parsed = _datetime(item, key, where, required=True)
    assert parsed is not None
    return parsed


def _raw(item: Mapping[str, Any], where: str) -> Mapping[str, Any]:
    value = item.get("raw")
    if value is None:
        return {}
    return _mapping(value, f"{where}.raw")


def _strict_bool(item: Mapping[str, Any], key: str, where: str) -> bool:
    value = item.get(key)
    if not isinstance(value, bool):
        raise TransportExportContractError(f"{where}.{key}: boolean이어야 한다.")
    return value


def parse_collection(value: Any, *, where: str) -> TransportCollection:
    """``collection``을 엄격히 읽는다. 플래그가 빠지면 신선도를 알 수 없으니 계약 위반이다."""
    body = _mapping(value, f"{where}.collection")
    return TransportCollection(
        source=_required_text(body, "source", f"{where}.collection"),
        last_success_at=_datetime(body, "last_success_at", f"{where}.collection", required=False),
        failed=_strict_bool(body, "failed", f"{where}.collection"),
        stale=_strict_bool(body, "stale", f"{where}.collection"),
    )


def require_current_collection(collection: TransportCollection, *, where: str) -> None:
    """이력 없음·실패·stale이면 :class:`TransportExportNotCurrent`.

    transport는 이 경우 503을 내야 한다(transport ADR-013). 200인데 플래그가 서 있으면 transport가
    계약을 어긴 것이지만, 결과는 같다 — 그 집합으로 reconcile하지 않는다.
    """
    if collection.last_success_at is None:
        raise TransportExportNotCurrent(f"{where}: {collection.source} 수집 이력이 없다.")
    if collection.failed:
        raise TransportExportNotCurrent(f"{where}: {collection.source} 마지막 수집이 실패했다.")
    if collection.stale:
        raise TransportExportNotCurrent(f"{where}: {collection.source} 수집이 stale이다.")


def require_fresh_incident_set(
    active: TransportIncidentActiveSet,
    *,
    now: datetime,
    max_age: timedelta = INCIDENT_SET_MAX_AGE,
) -> None:
    """돌발 집합이 지금의 활성 집합인지 Map 쪽에서도 잰다(transport 503에만 기대지 않는다)."""
    require_current_collection(active.collection, where="highway-incidents/active")
    age = now - active.collected_at
    if age > max_age:
        raise TransportExportNotCurrent(
            f"highway-incidents/active: collected_at이 {age}만큼 지났다(상한 {max_age})."
        )
    if age < -max_age:
        # 시계가 크게 어긋났다 — 미래 집합을 "지금"으로 믿으면 종료 판단이 틀어진다.
        raise TransportExportNotCurrent(
            f"highway-incidents/active: collected_at이 {-age}만큼 미래다(시계 불일치)."
        )


def parse_export_page(payload: Any, *, where: str) -> TransportExportPage:
    """페이지 envelope을 검사한다. ``has_more=true``면 새 ``next_cursor``가 있어야 한다."""
    page = _mapping(payload, where)
    items = page.get("items")
    if not isinstance(items, list):
        raise TransportExportContractError(f"{where}.items: 배열이어야 한다.")
    has_more = page.get("has_more")
    if not isinstance(has_more, bool):
        raise TransportExportContractError(f"{where}.has_more: boolean이어야 한다.")
    next_cursor = page.get("next_cursor")
    if has_more and (not isinstance(next_cursor, str) or not next_cursor):
        raise TransportExportContractError(f"{where}: has_more=true인데 next_cursor가 없다.")
    return TransportExportPage(
        items=tuple(_mapping(item, f"{where}.items[]") for item in items),
        next_cursor=next_cursor if isinstance(next_cursor, str) else None,
        has_more=has_more,
        collection=parse_collection(page.get("collection"), where=where),
    )


def parse_fuel_station(item: Mapping[str, Any]) -> TransportFuelStation:
    where = "fuel-stations.item"
    prices_value = item.get("prices")
    if not isinstance(prices_value, list):
        raise TransportExportContractError(f"{where}.prices: 배열이어야 한다.")
    prices: list[TransportFuelPrice] = []
    for raw_price in prices_value:
        price = _mapping(raw_price, f"{where}.prices[]")
        prices.append(TransportFuelPrice(
            product_code=_required_text(price, "product_code", f"{where}.prices[]"),
            price=_decimal(price, "price", f"{where}.prices[]"),
            provider_updated_at=_datetime(
                price, "provider_updated_at", f"{where}.prices[]", required=False
            ),
            observed_at=_required_datetime(price, "observed_at", f"{where}.prices[]"),
            collected_at=_required_datetime(price, "collected_at", f"{where}.prices[]"),
            raw=dict(price),
        ))
    lpg = next((price for price in prices if price.product_code == "K015"), None)
    return TransportFuelStation(
        uni_id=_required_text(item, "natural_key", where).strip(),
        name=_required_text(item, "name", where),
        brand=_text(item, "brand_code", where),
        brand_name=_text(item, "brand_name", where),
        address_road=_text(item, "address", where),
        address_jibun=None,
        lon=_number(item, "longitude", where),
        lat=_number(item, "latitude", where),
        tel=_text(item, "phone", where),
        # 오피넷 브라우저 원천에는 LPG 여부 컬럼이 없다.
        # LPG(K015) 가격 행이 판매가를 가지면 판매로 본다.
        lpg_yn=None if lpg is None else lpg.price is not None,
        is_self=_bool(item, "is_self", where),
        is_24h=_bool(item, "is_24h", where),
        has_carwash=_bool(item, "has_carwash", where),
        has_maintenance=_bool(item, "has_maintenance", where),
        has_cvs=_bool(item, "has_cvs", where),
        last_seen_at=_required_datetime(item, "last_seen_at", where),
        prices=tuple(prices),
        raw=_raw(item, where),
    )


def parse_rest_area(item: Mapping[str, Any]) -> TransportRestArea:
    where = "rest-areas.item"
    return TransportRestArea(
        natural_key=_required_text(item, "natural_key", where),
        name=_required_text(item, "name", where),
        route_name=_text(item, "route_name", where),
        direction=_text(item, "direction", where),
        lon=_number(item, "longitude", where),
        lat=_number(item, "latitude", where),
        phone_number=_text(item, "phone_number", where),
        has_gas_station=_bool(item, "has_gas_station", where),
        has_lpg_station=_bool(item, "has_lpg_station", where),
        has_ev_charger=_bool(item, "has_ev_charger", where),
        raw=_raw(item, where),
    )


def parse_rest_area_fuel_price(item: Mapping[str, Any]) -> TransportRestAreaFuelPrice:
    where = "rest-area-fuel-prices.item"
    return TransportRestAreaFuelPrice(
        service_area_code=_required_text(item, "service_area_code", where).strip(),
        route_name=_text(item, "route_name", where),
        direction=_text(item, "direction", where),
        oil_company=_text(item, "oil_company", where),
        service_area_name=_text(item, "service_area_name", where),
        phone_number=_text(item, "phone_number", where),
        address=_text(item, "address", where),
        gasoline_price=_integer(item, "gasoline_price", where),
        diesel_price=_integer(item, "diesel_price", where),
        lpg_price=_integer(item, "lpg_price", where),
        observed_at=_required_datetime(item, "observed_at", where),
        raw=_raw(item, where),
    )


def _parse_incident(item: Mapping[str, Any]) -> TransportHighwayIncident:
    where = "highway-incidents.item"
    return TransportHighwayIncident(
        occurred_date=_text(item, "occurred_date", where),
        occurred_time=_text(item, "occurred_time", where),
        incident_type=_text(item, "incident_type", where),
        incident_type_code=_text(item, "incident_type_code", where),
        direction=_text(item, "direction", where),
        message=_text(item, "message", where),
        point_name=_text(item, "point_name", where),
        route_no=_text(item, "route_no", where),
        route_name=_text(item, "route_name", where),
        process_status=_text(item, "process_status", where),
        process_status_code=_text(item, "process_status_code", where),
        latitude=_number(item, "latitude", where),
        longitude=_number(item, "longitude", where),
        congestion_length=_number(item, "congestion_length", where),
        series_no=_integer(item, "series_no", where),
        raw=_raw(item, where),
    )


def parse_active_incident_set(payload: Any) -> TransportIncidentActiveSet:
    """활성 돌발 집합을 검사한다. 원본 provider 행(``raw``)이 없는 사건은 계약 위반이다."""
    where = "highway-incidents/active"
    body = _mapping(payload, where)
    items = body.get("items")
    if not isinstance(items, list):
        raise TransportExportContractError(f"{where}.items: 배열이어야 한다.")
    parsed = tuple(_parse_incident(_mapping(item, f"{where}.items[]")) for item in items)
    if any(not incident.raw for incident in parsed):
        raise TransportExportContractError(f"{where}: 원본 행(raw)이 없는 사건이 있다.")
    return TransportIncidentActiveSet(
        collected_at=_required_datetime(body, "collected_at", where),
        items=parsed,
        collection=parse_collection(body.get("collection"), where=where),
    )


def parse_airport(item: Mapping[str, Any]) -> TransportAirport:
    where = "airports.item"
    lat = _number(item, "latitude", where)
    lon = _number(item, "longitude", where)
    return TransportAirport(
        code=_required_text(item, "code", where).strip().upper(),
        name_korean=_text(item, "name_korean", where),
        name_english=_required_text(item, "name_english", where),
        icao_code=_text(item, "icao_code", where),
        municipality=_text(item, "municipality", where),
        coordinate=(
            TransportCoordinate(lat=lat, lon=lon) if lat is not None and lon is not None else None
        ),
        raw=dict(item),
    )


def parse_airports(payload: Any) -> tuple[TransportAirport, ...]:
    body = _mapping(payload, "airports")
    items = body.get("items")
    if not isinstance(items, list):
        raise TransportExportContractError("airports.items: 배열이어야 한다.")
    if not items:
        # 다른 완전 snapshot export와 같은 분류다 — 0건을 "공항 전부 폐쇄"로 읽지 않는다.
        raise TransportExportEmpty("kor-travel-transport airports가 0건이다.")
    return tuple(parse_airport(_mapping(item, "airports.items[]")) for item in items)


@dataclass(frozen=True, slots=True)
class TransportFuelPriceHistoryPoint:
    """가격 이력 한 행. ``price=None``은 그때 판매하지 않음이다(null은 그대로 둔다).

    transport T4 행은 ``product_code``·``observed_at``·``price``만 준다. ``provider_updated_at``·
    ``collected_at``은 원천이 행마다 주지 않으므로 ``None``이다 — 응답 생성 시각 등으로 채우지
    않는다(값이 오면 엄격히 읽는다).
    """

    product_code: str
    price: Decimal | None
    observed_at: datetime
    provider_updated_at: datetime | None = None
    collected_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TransportFuelPriceHistory:
    """``GET …/fuel-stations/{station_key}/price-history`` 한 페이지(transport T4).

    ``items``는 ``observed_at`` 내림차순이다. ``has_more``이면 ``next_cursor``로 다음 페이지를
    읽는다.
    ``source_status``는 ``ok``/``stale``(stale이어도 기존 이력은 200으로 온다).
    """

    station_key: str
    generated_at: datetime
    source_collected_at: datetime | None
    source_status: PriceHistorySourceStatus
    items: tuple[TransportFuelPriceHistoryPoint, ...]
    has_more: bool
    next_cursor: str | None


def parse_fuel_price_history(
    payload: Any,
    *,
    station_key: str,
    product_code: str | None = None,
    observed_from: datetime | None = None,
    observed_to: datetime | None = None,
) -> TransportFuelPriceHistory:
    """가격 이력 한 페이지를 엄격히 읽는다(transport ``FuelPriceHistoryExportPage``).

    요청한 주유소가 아닌 응답·``meta.item_count``와 행 수 불일치·``has_more``와 ``next_cursor``의
    어긋남·``observed_at`` 내림차순 위반·문자열이거나 유한하지 않은 가격은 계약 위반이다.

    요청 조건도 행마다 확인한다: ``product_code``를 보냈으면 모든 행이 그 유종이어야 하고,
    ``observed_from``/``observed_to``(보낸 ``from``/``to`` — transport는 양끝 포함)를 보냈으면 모든
    ``observed_at``이 그 안이어야 한다. 보내지 않은 끝은 transport 기본값을 추측하지 않고 검사하지
    않는다.
    """
    where = "fuel-stations/price-history"
    body = _mapping(payload, where)
    returned_key = _required_text(body, "station_key", where)
    if returned_key != station_key:
        raise TransportExportContractError(
            f"{where}.station_key: 요청({station_key!r})과 다른 주유소({returned_key!r})다."
        )
    meta = _mapping(body.get("meta"), f"{where}.meta")
    raw_status = _required_text(meta, "source_status", f"{where}.meta")
    source_status = _PRICE_HISTORY_SOURCE_STATUSES.get(raw_status)
    if source_status is None:
        raise TransportExportContractError(
            f"{where}.meta.source_status: 알 수 없는 값({raw_status!r})이다."
        )
    item_count = meta.get("item_count")
    if isinstance(item_count, bool) or not isinstance(item_count, int):
        raise TransportExportContractError(f"{where}.meta.item_count: 정수여야 한다.")
    items = body.get("items")
    if not isinstance(items, list):
        raise TransportExportContractError(f"{where}.items: 배열이어야 한다.")
    if item_count != len(items):
        raise TransportExportContractError(
            f"{where}.meta.item_count({item_count})가 items 수({len(items)})와 다르다."
        )
    points: list[TransportFuelPriceHistoryPoint] = []
    row_where = f"{where}.items[]"
    for raw in items:
        row = _mapping(raw, row_where)
        point = TransportFuelPriceHistoryPoint(
            product_code=_required_text(row, "product_code", row_where).strip(),
            price=_json_number(row, "price", row_where),
            observed_at=_required_datetime(row, "observed_at", row_where),
            provider_updated_at=_datetime(row, "provider_updated_at", row_where, required=False),
            collected_at=_datetime(row, "collected_at", row_where, required=False),
        )
        if points and point.observed_at > points[-1].observed_at:
            raise TransportExportContractError(f"{where}.items: observed_at 내림차순이 아니다.")
        if product_code is not None and point.product_code != product_code:
            raise TransportExportContractError(
                f"{where}.items: 요청 유종({product_code!r})이 아닌 행({point.product_code!r})이다."
            )
        if (observed_from is not None and point.observed_at < observed_from) or (
            observed_to is not None and point.observed_at > observed_to
        ):
            raise TransportExportContractError(
                f"{where}.items: observed_at({point.observed_at.isoformat()})이 요청 창 밖이다."
            )
        points.append(point)
    has_more = _strict_bool(body, "has_more", where)
    next_cursor = _text(body, "next_cursor", where)
    if has_more != bool(next_cursor):
        raise TransportExportContractError(
            f"{where}: has_more({has_more})와 next_cursor 유무가 어긋난다."
        )
    return TransportFuelPriceHistory(
        station_key=returned_key,
        generated_at=_required_datetime(meta, "generated_at", f"{where}.meta"),
        source_collected_at=_datetime(
            meta, "source_collected_at", f"{where}.meta", required=False
        ),
        source_status=source_status,
        items=tuple(points),
        has_more=has_more,
        next_cursor=next_cursor,
    )
