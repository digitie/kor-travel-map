"""``krtour.map.geocoding`` — ``kraddr-geo`` **REST API v2** 연동.

좌표 ↔ 행정구역 보강(정/역지오코딩)을 본 라이브러리 ``Address`` / ``Coordinate``
DTO로 정규화한다. geocoding 엔진은 별도 서비스 **``kraddr-geo``** (FastAPI,
``/v1/address/*``)가 담당하고, 본 모듈은 그 **REST 응답**(``ReverseResponse`` /
``GeocodeResponse``, API version 2.0)을 본 라이브러리 DTO로 옮기는 **순수 변환
함수** + HTTP 클라이언트 + 비동기 콜러블 어댑터만 둔다.

전환 배경 (python API → REST API v2)
------------------------------------
이전 구현은 ``kraddr-geo`` **in-process python 클라이언트**(``AsyncAddressClient``)의
``reverse_v2``/``geocode_v2``를 가정했으나, 그 메서드는 현재 ``kraddr-geo``에
존재하지 않으며(API 미존재), python 클라이언트는 ``kraddr-geo`` **자체 DB
엔진**을 필요로 해 강한 결합을 만든다. 따라서 ``kraddr-geo``를 **독립 REST
서비스**로 호출하도록 전환한다 (호출 측은 서비스 URL만 알면 되고, DB/패키지
의존이 사라진다). 코드 변환 기준은 ``docs/address-geocoding.md`` 참조.

설계 — ADR-006(provider wrapper 금지) 정신 동일
------------------------------------------------
- ``kraddr-geo`` / ``httpx``를 **런타임 import 하지 않는다**. REST 응답
  (``ReverseResponse``/``GeocodeResponse``/``AddressStructure``/``Point``/
  ``GeocodeExtension``)의 **structural Protocol**만 정의하고, 호출 측이
  주입한 ``httpx.AsyncClient``로 HTTP를 친다 (ADR-044 — 정합성 1차 책임은
  kraddr-geo).
- 변환 함수(``reverse_response_to_address``/``geocode_response_to_coordinate``)는
  동기·순수라 ``kraddr-geo``/HTTP 없이 fake 응답으로 단위 테스트된다.
- async 콜러블 팩토리(``kraddr_geo_reverse_geocoder``/``kraddr_geo_address_geocoder``)는
  ``KraddrGeoRestClient``를 받아 ``ReverseGeocoder`` / ``AddressGeocoder`` 콜러블을
  만든다. ``httpx.AsyncClient`` 수명(base_url 설정/close)은 호출자 책임 (ADR-002).

**철칙**: 주소 문자열만으로 법정동코드 추정 금지 — reverse geocoding 결과
(좌표 기반)만 신뢰.

ADR 참조
--------
- ADR-002 — 순수 함수 + async-only client
- ADR-006 — provider 직접 사용 (wrapper class 금지), 구조 Protocol 입력 + client 주입
- ADR-012 — ``Coordinate``는 WGS84 (lon/lat)
- ADR-041 — 주소 DTO/utility는 본 라이브러리 흡수 (kraddr-base)
- ADR-044 — kraddr-geo 데이터 정합성 1차 책임은 kraddr-geo (REST 응답 신뢰·미러)
"""

from __future__ import annotations

import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from krtour.map.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_bjd_code,
    normalize_korean_text,
)
from krtour.map.dto import Address, Coordinate

if TYPE_CHECKING:
    import httpx

__all__ = [
    # 비동기 콜러블 계약 (docs/address-geocoding.md §2)
    "AddressGeocoder",
    "ReverseGeocoder",
    "cached_reverse_geocoder",
    # kraddr-geo REST v2 응답 structural Protocol
    "KraddrPoint",
    "KraddrAddressStructure",
    "KraddrReverseResultItem",
    "KraddrReverseResponse",
    "KraddrGeocodeResult",
    "KraddrGeocodeExtension",
    "KraddrGeocodeResponse",
    # 순수 변환 함수
    "reverse_response_to_address",
    "geocode_response_to_coordinate",
    # REST client + 콜러블 팩토리
    "KraddrGeoRestClient",
    "kraddr_geo_reverse_geocoder",
    "kraddr_geo_address_geocoder",
]


# -- 비동기 콜러블 계약 --------------------------------------------------------
#
# docs/address-geocoding.md §2. provider 적재 파이프라인이 받는 enrichment
# resource — async-only (ADR-002). standard_data.ReverseGeocoder(동기 Protocol)와
# 구분된다 (그쪽은 sync lookup table용).

AddressGeocoder = Callable[[Address], Awaitable[Coordinate | None]]
"""정지오코딩: ``Address`` → ``Coordinate | None`` (await)."""

ReverseGeocoder = Callable[[Coordinate], Awaitable[Address | None]]
"""역지오코딩: ``Coordinate`` → ``Address | None`` (await)."""


# -- 역지오코딩 결과 캐싱 (async) ---------------------------------------------
#
# provider 변환 함수는 모두 async이고 feature_id가 bjd_code에 의존(ADR-009)하므로,
# 변환기는 feature_id 계산 전에 ``await reverse_geocoder(coord)``로 ``Address``를
# 채운다. 같은 batch 안의 중복 좌표를 반복 호출하지 않도록 변환기는 주입받은
# geocoder를 ``cached_reverse_geocoder``로 감싸 메모이즈한다.

_DEFAULT_COORD_PRECISION = 6
"""좌표 캐시 키 소수 자릿수 (1e-6° ≈ 0.11m — 같은 시설 묶기 충분)."""


def cached_reverse_geocoder(
    geocoder: ReverseGeocoder,
    *,
    precision: int = _DEFAULT_COORD_PRECISION,
) -> ReverseGeocoder:
    """``ReverseGeocoder``를 좌표(precision 자리 양자화) 기준 메모이즈한다.

    반환 콜러블은 호출 수명 동안 결과(``Address | None`` 포함)를 캐싱 — batch
    변환에서 중복 좌표의 역지오코딩 round-trip을 1회로 줄인다. ``None`` 결과도
    캐싱하므로 실패 좌표를 재시도하지 않는다.
    """
    cache: dict[tuple[str, str], Address | None] = {}

    async def _cached(coord: Coordinate) -> Address | None:
        key = (f"{coord.lon:.{precision}f}", f"{coord.lat:.{precision}f}")
        if key not in cache:
            cache[key] = await geocoder(coord)
        return cache[key]

    return _cached


# -- kraddr-geo REST v2 응답 structural Protocol ------------------------------
#
# kraddr.geo.dto 모델과 필드명 1:1 (kraddr-geo를 import하지 않고 구조만 의존).
# AddressStructure는 vworld 호환 level 명명: level1=시도 / level2=시군구 /
# level4L=법정리·읍면동 / level4LC=법정동코드(10) / level4A=행정동 /
# level4AC=행정동코드(10) / level5=도로명 (kraddr.geo.core.responses 참조).


@runtime_checkable
class KraddrPoint(Protocol):
    """kraddr-geo ``Point`` — ``x=lon`` / ``y=lat`` (WGS84)."""

    @property
    def x(self) -> float: ...
    @property
    def y(self) -> float: ...


@runtime_checkable
class KraddrAddressStructure(Protocol):
    """kraddr-geo ``AddressStructure`` — vworld 호환 level 구조."""

    @property
    def level1(self) -> str | None: ...
    @property
    def level2(self) -> str | None: ...
    @property
    def level4L(self) -> str | None: ...
    @property
    def level4LC(self) -> str | None: ...
    @property
    def level4A(self) -> str | None: ...
    @property
    def level4AC(self) -> str | None: ...
    @property
    def level5(self) -> str | None: ...
    @property
    def detail(self) -> str | None: ...


@runtime_checkable
class KraddrReverseResultItem(Protocol):
    """kraddr-geo ``ReverseResultItem`` — reverse 결과 1건 (road 또는 parcel)."""

    @property
    def type(self) -> str: ...
    @property
    def text(self) -> str: ...
    @property
    def structure(self) -> KraddrAddressStructure: ...
    @property
    def point(self) -> KraddrPoint | None: ...
    @property
    def zipcode(self) -> str | None: ...
    @property
    def distance_m(self) -> float | None: ...


@runtime_checkable
class KraddrReverseResponse(Protocol):
    """kraddr-geo ``ReverseResponse``."""

    @property
    def status(self) -> str: ...
    @property
    def result(self) -> tuple[KraddrReverseResultItem, ...]: ...


@runtime_checkable
class KraddrGeocodeResult(Protocol):
    """kraddr-geo ``GeocodeResult`` — 정지오코딩 좌표."""

    @property
    def point(self) -> KraddrPoint: ...


@runtime_checkable
class KraddrGeocodeExtension(Protocol):
    """kraddr-geo ``GeocodeExtension`` — confidence + 코드 보강."""

    @property
    def confidence(self) -> float: ...
    @property
    def bjd_cd(self) -> str | None: ...
    @property
    def rncode_full(self) -> str | None: ...
    @property
    def zip_no(self) -> str | None: ...


@runtime_checkable
class KraddrGeocodeResponse(Protocol):
    """kraddr-geo ``GeocodeResponse``."""

    @property
    def status(self) -> str: ...
    @property
    def result(self) -> KraddrGeocodeResult | None: ...
    @property
    def x_extension(self) -> KraddrGeocodeExtension | None: ...


# -- 내부 helper --------------------------------------------------------------

_FIVE_DIGITS = re.compile(r"^\d{5}$")
_TEN_DIGITS = re.compile(r"^\d{10}$")
_STATUS_OK = "OK"
_TYPE_ROAD = "road"
_TYPE_PARCEL = "parcel"


def _digits_or_none(value: str | None, pattern: re.Pattern[str]) -> str | None:
    """``value``가 패턴(자릿수)에 맞으면 그대로, 아니면 ``None`` (검증 거부 회피)."""
    if value is None:
        return None
    text = value.strip()
    return text if pattern.match(text) else None


def _closest_item(
    items: tuple[KraddrReverseResultItem, ...],
) -> KraddrReverseResultItem:
    """``distance_m`` 최소 항목 (None은 뒤로). items는 비어있지 않다고 가정."""
    return min(
        items,
        key=lambda it: it.distance_m if it.distance_m is not None else math.inf,
    )


# -- 순수 변환 함수 -----------------------------------------------------------


def reverse_response_to_address(
    response: KraddrReverseResponse,
    *,
    max_distance_m: float | None = None,
) -> Address | None:
    """kraddr-geo ``reverse`` 응답 → 본 라이브러리 ``Address``.

    ``status != "OK"`` 이거나 (거리 필터 적용 후) 결과가 없으면 ``None``.
    가장 가까운 항목을 대표(코드·명칭)로, road/parcel 항목 text를 각각
    ``road``/``legal``에 채운다.

    매핑 (``docs/address-geocoding.md`` / kraddr.geo.core.responses)
        - ``bjd_code`` ← ``structure.level4LC`` (법정동코드 10자리)
        - ``sigungu_code`` / ``sido_code`` ← bjd_code에서 파생
        - ``admin_dong_code`` ← ``structure.level4AC`` (10자리만)
        - ``road`` ← road 항목 ``text`` (없으면 ``structure.level5`` 도로명)
        - ``legal`` ← parcel 항목 ``text``
        - ``admin`` ← ``structure.level4A``(행정동) 또는 ``level4L``
        - ``zipcode`` ← 대표 항목 ``zipcode`` (5자리만)
        - ``sido_name``/``sigungu_name`` ← ``structure.level1``/``level2``

    Notes
    -----
    reverse ``AddressStructure``에는 도로명코드가 없어 ``road_name_code``는
    채우지 않는다 (geocode ``x_extension.rncode_full``에만 존재). 잘못된 자릿수
    코드/우편번호는 ``None``으로 떨어뜨려 ``Address`` validator 거부를 피한다.
    """
    if response.status != _STATUS_OK or not response.result:
        return None
    items = response.result
    if max_distance_m is not None:
        items = tuple(
            it
            for it in items
            if it.distance_m is None or it.distance_m <= max_distance_m
        )
        if not items:
            return None

    primary = _closest_item(items)
    struct = primary.structure
    road_text = next((it.text for it in items if it.type == _TYPE_ROAD), None)
    parcel_text = next((it.text for it in items if it.type == _TYPE_PARCEL), None)

    # `normalize_bjd_code`는 비-10자리 입력에 `ValueError` raise — kraddr-geo가
    # 어쩌다 비정형 `level4LC`(예: 짧은 임시 코드)를 돌려줘도 reverse 전체가
    # 깨지지 않도록 graceful drop (None 처리, Address validator도 None 허용).
    try:
        bjd_code = normalize_bjd_code(struct.level4LC)
    except ValueError:
        bjd_code = None
    return Address(
        road=normalize_korean_text(road_text or struct.level5),
        legal=normalize_korean_text(parcel_text),
        admin=normalize_korean_text(struct.level4A or struct.level4L),
        bjd_code=bjd_code,
        admin_dong_code=_digits_or_none(struct.level4AC, _TEN_DIGITS),
        sigungu_code=extract_sigungu_code(bjd_code),
        sido_code=extract_sido_code(bjd_code),
        road_name_code=None,
        zipcode=_digits_or_none(primary.zipcode, _FIVE_DIGITS),
        sido_name=normalize_korean_text(struct.level1),
        sigungu_name=normalize_korean_text(struct.level2),
    )


def geocode_response_to_coordinate(
    response: KraddrGeocodeResponse,
    *,
    min_confidence: float = 0.0,
) -> Coordinate | None:
    """kraddr-geo ``geocode`` 응답 → ``Coordinate`` (WGS84).

    ``status != "OK"`` 이거나 ``result`` 좌표가 없으면 ``None``.
    ``x_extension.confidence``가 ``min_confidence`` 미만이면 ``None``.
    ``result.point.x/y``를 lon/lat으로.
    """
    if response.status != _STATUS_OK or response.result is None:
        return None
    ext = response.x_extension
    if ext is not None and ext.confidence < min_confidence:
        return None
    point = response.result.point
    try:
        return Coordinate(
            lon=Decimal(str(point.x)),
            lat=Decimal(str(point.y)),
        )
    except (InvalidOperation, ValueError):
        return None


# -- kraddr-geo REST 응답 파싱용 frozen dataclass (Protocol 만족) ---------------


@dataclass(frozen=True)
class _RestPoint:
    x: float
    y: float


@dataclass(frozen=True)
class _RestStructure:
    level1: str | None = None
    level2: str | None = None
    level4L: str | None = None
    level4LC: str | None = None
    level4A: str | None = None
    level4AC: str | None = None
    level5: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class _RestReverseItem:
    type: str
    text: str
    structure: _RestStructure
    point: _RestPoint | None = None
    zipcode: str | None = None
    distance_m: float | None = None


@dataclass(frozen=True)
class _RestReverseResponse:
    status: str
    result: tuple[_RestReverseItem, ...] = ()


@dataclass(frozen=True)
class _RestGeocodeResult:
    point: _RestPoint


@dataclass(frozen=True)
class _RestGeocodeExtension:
    confidence: float = 0.0
    bjd_cd: str | None = None
    rncode_full: str | None = None
    zip_no: str | None = None


@dataclass(frozen=True)
class _RestGeocodeResponse:
    status: str
    result: _RestGeocodeResult | None = None
    x_extension: _RestGeocodeExtension | None = None


def _parse_point(data: dict[str, Any] | None) -> _RestPoint | None:
    if not data:
        return None
    return _RestPoint(x=float(data["x"]), y=float(data["y"]))


def _parse_structure(data: dict[str, Any] | None) -> _RestStructure:
    data = data or {}
    return _RestStructure(
        level1=data.get("level1"),
        level2=data.get("level2"),
        level4L=data.get("level4L"),
        level4LC=data.get("level4LC"),
        level4A=data.get("level4A"),
        level4AC=data.get("level4AC"),
        level5=data.get("level5"),
        detail=data.get("detail"),
    )


def _parse_reverse_response(data: dict[str, Any]) -> _RestReverseResponse:
    items = tuple(
        _RestReverseItem(
            type=str(item.get("type", "")),
            text=str(item.get("text", "")),
            structure=_parse_structure(item.get("structure")),
            point=_parse_point(item.get("point")),
            zipcode=item.get("zipcode"),
            distance_m=(
                float(item["distance_m"]) if item.get("distance_m") is not None else None
            ),
        )
        for item in data.get("result", ())
    )
    return _RestReverseResponse(status=str(data.get("status", "ERROR")), result=items)


def _parse_geocode_response(data: dict[str, Any]) -> _RestGeocodeResponse:
    result_data = data.get("result")
    point = _parse_point(result_data.get("point")) if result_data else None
    result = _RestGeocodeResult(point=point) if point is not None else None
    ext_data = data.get("x_extension")
    extension = (
        _RestGeocodeExtension(
            confidence=float(ext_data.get("confidence", 0.0)),
            bjd_cd=ext_data.get("bjd_cd"),
            rncode_full=ext_data.get("rncode_full"),
            zip_no=ext_data.get("zip_no"),
        )
        if ext_data
        else None
    )
    return _RestGeocodeResponse(
        status=str(data.get("status", "ERROR")),
        result=result,
        x_extension=extension,
    )


# -- kraddr-geo REST 클라이언트 -----------------------------------------------


class KraddrGeoRestClient:
    """kraddr-geo REST API v2 (``/v1/address/*``) 비동기 클라이언트.

    ``httpx.AsyncClient``를 주입받아 ``GET /v1/address/reverse`` /
    ``GET /v1/address/geocode``를 호출하고 JSON을 structural 응답 객체로 파싱한다.
    호스트는 주입한 ``httpx.AsyncClient``의 ``base_url``로 설정 (로컬 개발 예:
    ``httpx.AsyncClient(base_url="http://127.0.0.1:8888")``), 경로 prefix는
    ``base_path`` (기본 ``/v1``). client 수명은 호출자 책임 (ADR-002).
    """

    def __init__(
        self, http_client: httpx.AsyncClient, *, base_path: str = "/v1"
    ) -> None:
        self._http = http_client
        self._base = base_path.rstrip("/")

    async def reverse(
        self,
        x: float,
        y: float,
        *,
        type_: Literal["both", "road", "parcel"] = "both",
        zipcode: bool = True,
        radius_m: int | None = None,
    ) -> _RestReverseResponse:
        """``GET /v1/address/reverse`` — 좌표(x=lon, y=lat) 역지오코딩."""
        params: dict[str, Any] = {
            "x": x,
            "y": y,
            "type": type_,
            "zipcode": str(zipcode).lower(),
        }
        if radius_m is not None:
            params["radius_m"] = radius_m
        resp = await self._http.get(f"{self._base}/address/reverse", params=params)
        resp.raise_for_status()
        return _parse_reverse_response(resp.json())

    async def geocode(
        self,
        address: str,
        *,
        type_: Literal["road", "parcel"] = "road",
        refine: bool = True,
        fallback: Literal["off", "local_only", "api"] = "local_only",
    ) -> _RestGeocodeResponse:
        """``GET /v1/address/geocode`` — 주소 문자열 정지오코딩."""
        params: dict[str, Any] = {
            "address": address,
            "type": type_,
            "refine": str(refine).lower(),
            "fallback": fallback,
        }
        resp = await self._http.get(f"{self._base}/address/geocode", params=params)
        resp.raise_for_status()
        return _parse_geocode_response(resp.json())


# -- kraddr-geo REST client → 콜러블 팩토리 -----------------------------------


def kraddr_geo_reverse_geocoder(
    client: KraddrGeoRestClient,
    *,
    type_: Literal["both", "road", "parcel"] = "both",
    radius_m: int | None = None,
    max_distance_m: float | None = None,
) -> ReverseGeocoder:
    """kraddr-geo REST client → ``ReverseGeocoder`` (좌표 → ``Address``) 콜러블.

    Examples
    --------
    >>> # import httpx
    >>> # async with httpx.AsyncClient(base_url="http://127.0.0.1:8888") as http:
    >>> #     client = KraddrGeoRestClient(http)
    >>> #     reverse = kraddr_geo_reverse_geocoder(client)
    >>> #     addr = await reverse(Coordinate(lon=Decimal("127.0"), lat=Decimal("37.5")))
    """

    async def _reverse(coord: Coordinate) -> Address | None:
        response = await client.reverse(
            float(coord.lon), float(coord.lat), type_=type_, radius_m=radius_m
        )
        return reverse_response_to_address(response, max_distance_m=max_distance_m)

    return _reverse


def kraddr_geo_address_geocoder(
    client: KraddrGeoRestClient,
    *,
    min_confidence: float = 0.0,
    fallback: Literal["off", "local_only", "api"] = "local_only",
) -> AddressGeocoder:
    """kraddr-geo REST client → ``AddressGeocoder`` (``Address`` → 좌표) 콜러블.

    ``Address.road``(도로명)가 있으면 ``type=road``, 없으면 ``Address.legal``
    (지번)으로 ``type=parcel`` 조회. 둘 다 없으면 ``None``.
    """

    async def _geocode(address: Address) -> Coordinate | None:
        query: str
        addr_type: Literal["road", "parcel"]
        if address.road:
            query, addr_type = address.road, "road"
        elif address.legal:
            query, addr_type = address.legal, "parcel"
        else:
            return None
        response = await client.geocode(query, type_=addr_type, fallback=fallback)
        return geocode_response_to_coordinate(response, min_confidence=min_confidence)

    return _geocode
