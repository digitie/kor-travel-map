"""``krtour.map.geocoding`` — ``kraddr-geo`` **REST API v2** 연동.

좌표 ↔ 행정구역 보강(정/역지오코딩)을 본 라이브러리 ``Address`` / ``Coordinate``
DTO로 정규화한다. geocoding 엔진은 별도 서비스 **``kraddr-geo``** (FastAPI,
provider-neutral ``POST /v2/{reverse,geocode}``)가 담당하고, 본 모듈은 그 **REST
응답**(``ReverseV2Response`` / ``GeocodeV2Response``)을 본 라이브러리 DTO로 옮기는
**순수 변환 함수** + HTTP 클라이언트 + 비동기 콜러블 어댑터만 둔다.

v2 (provider-neutral) 전환
--------------------------
이전 구현은 kraddr-geo ``GET /v1/address/{reverse,geocode}``(JUSO 호환,
``structure.level4LC`` 파싱)를 호출했으나, 현재 정본은 **``POST /v2/*``**
(``CandidateV2.address.legal_dong_code`` 등 **structured field 직접 제공** +
``confidence``/``distance_m``/``match_kind``)다. v2는 vworld level 파싱 없이
법정동코드를 바로 받으므로 본 모듈은 v2로 전환한다 (kraddr-geo
``src/kraddr/geo/dto/v2.py`` 정합).

설계 — ADR-006(provider wrapper 금지) 정신 동일
------------------------------------------------
- ``kraddr-geo`` / ``httpx``를 **런타임 import 하지 않는다**. REST 응답
  (``ReverseV2Response``/``GeocodeV2Response``/``CandidateV2``/``AddressV2``/
  ``RegionV2``/``Point``)의 **structural Protocol**만 정의하고, 호출 측이 주입한
  ``httpx.AsyncClient``로 HTTP를 친다 (ADR-044 — 정합성 1차 책임은 kraddr-geo).
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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
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
    "KraddrAddressV2",
    "KraddrRegionV2",
    "KraddrCandidateV2",
    "KraddrReverseV2Response",
    "KraddrGeocodeV2Response",
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
# kraddr.geo.dto.v2 모델과 필드명 1:1 (kraddr-geo를 import하지 않고 구조만 의존).
# CandidateV2.address.legal_dong_code(10) / admin_dong_code(10) / road_name_code /
# region.bjd_cd / region.sido / region.sigungu (kraddr.geo.dto.v2 참조).


@runtime_checkable
class KraddrPoint(Protocol):
    """kraddr-geo ``Point`` — ``x=lon`` / ``y=lat`` (WGS84)."""

    @property
    def x(self) -> float: ...
    @property
    def y(self) -> float: ...


@runtime_checkable
class KraddrAddressV2(Protocol):
    """kraddr-geo ``AddressV2`` — structured 주소 (코드 직접 제공)."""

    @property
    def full(self) -> str: ...
    @property
    def road_address(self) -> str | None: ...
    @property
    def parcel_address(self) -> str | None: ...
    @property
    def postal_code(self) -> str | None: ...
    @property
    def legal_dong_code(self) -> str | None: ...
    @property
    def admin_dong_code(self) -> str | None: ...
    @property
    def road_name(self) -> str | None: ...
    @property
    def road_name_code(self) -> str | None: ...


@runtime_checkable
class KraddrRegionV2(Protocol):
    """kraddr-geo ``RegionV2`` — 행정구역 명칭/코드."""

    @property
    def bjd_cd(self) -> str | None: ...
    @property
    def sido(self) -> str | None: ...
    @property
    def sigungu(self) -> str | None: ...
    @property
    def legal_dong(self) -> str | None: ...
    @property
    def admin_dong(self) -> str | None: ...


@runtime_checkable
class KraddrCandidateV2(Protocol):
    """kraddr-geo ``CandidateV2`` — reverse/geocode 결과 1건."""

    @property
    def confidence(self) -> float: ...
    @property
    def match_kind(self) -> str: ...
    @property
    def address(self) -> KraddrAddressV2 | None: ...
    @property
    def point(self) -> KraddrPoint | None: ...
    @property
    def distance_m(self) -> float | None: ...
    @property
    def region(self) -> KraddrRegionV2 | None: ...


@runtime_checkable
class KraddrReverseV2Response(Protocol):
    """kraddr-geo ``ReverseV2Response``."""

    @property
    def status(self) -> str: ...
    @property
    def candidates(self) -> tuple[KraddrCandidateV2, ...]: ...


@runtime_checkable
class KraddrGeocodeV2Response(Protocol):
    """kraddr-geo ``GeocodeV2Response``."""

    @property
    def status(self) -> str: ...
    @property
    def candidates(self) -> tuple[KraddrCandidateV2, ...]: ...


# -- 내부 helper --------------------------------------------------------------

_STATUS_OK = "OK"
_TYPE_ROAD = "road"
_TYPE_PARCEL = "parcel"


def _closest_candidate(
    candidates: tuple[KraddrCandidateV2, ...],
) -> KraddrCandidateV2:
    """``distance_m`` 최소 항목 (None은 뒤로). candidates는 비어있지 않다고 가정."""
    return min(
        candidates,
        key=lambda c: c.distance_m if c.distance_m is not None else math.inf,
    )


def _five_digits_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text if (len(text) == 5 and text.isdigit()) else None


# -- 순수 변환 함수 -----------------------------------------------------------


def reverse_response_to_address(
    response: KraddrReverseV2Response,
    *,
    max_distance_m: float | None = None,
) -> Address | None:
    """kraddr-geo ``POST /v2/reverse`` 응답 → 본 라이브러리 ``Address``.

    ``status != "OK"`` 이거나 (거리 필터 적용 후) candidate가 없으면 ``None``.
    가장 가까운 candidate를 대표(코드·명칭)로, road/parcel candidate를 각각
    ``road``/``legal``에 채운다. v2는 ``address.legal_dong_code``/``road_name_code``
    등을 직접 제공하므로 vworld level 파싱이 없다.

    매핑 (kraddr.geo.dto.v2)
        - ``bjd_code`` ← ``address.legal_dong_code`` (또는 ``region.bjd_cd``)
        - ``admin_dong_code`` ← ``address.admin_dong_code`` (10자리만)
        - ``road_name_code`` ← ``address.road_name_code``
        - ``sigungu_code`` / ``sido_code`` ← bjd_code에서 파생
        - ``road`` ← road candidate ``address.road_address`` (없으면 ``address.full``)
        - ``legal`` ← parcel candidate ``address.parcel_address``
        - ``admin`` ← ``region.admin_dong`` 또는 ``region.legal_dong``
        - ``zipcode`` ← 대표 candidate ``address.postal_code`` (5자리만)
        - ``sido_name``/``sigungu_name`` ← ``region.sido``/``region.sigungu``

    Notes
    -----
    잘못된 자릿수 코드/우편번호는 ``None``으로 떨어뜨려 ``Address`` validator 거부를
    피한다 (kraddr-geo가 비정형 코드를 돌려줘도 reverse 전체가 깨지지 않게).
    """
    if response.status != _STATUS_OK or not response.candidates:
        return None
    cands = response.candidates
    if max_distance_m is not None:
        cands = tuple(
            c
            for c in cands
            if c.distance_m is None or c.distance_m <= max_distance_m
        )
        if not cands:
            return None

    primary = _closest_candidate(cands)
    paddr = primary.address
    region = primary.region

    road_addr = next(
        (
            c.address.road_address
            for c in cands
            if c.match_kind == _TYPE_ROAD and c.address is not None
        ),
        None,
    )
    parcel_addr = next(
        (
            c.address.parcel_address
            for c in cands
            if c.match_kind == _TYPE_PARCEL and c.address is not None
        ),
        None,
    )

    # legal_dong_code 우선, 없으면 region.bjd_cd. 비-10자리는 graceful drop.
    raw_bjd = (paddr.legal_dong_code if paddr else None) or (
        region.bjd_cd if region else None
    )
    try:
        bjd_code = normalize_bjd_code(raw_bjd)
    except ValueError:
        bjd_code = None

    admin_dong_code = paddr.admin_dong_code if paddr else None
    if admin_dong_code is not None and not (
        len(admin_dong_code) == 10 and admin_dong_code.isdigit()
    ):
        admin_dong_code = None

    road_value = road_addr or (paddr.road_address if paddr else None) or (
        paddr.full if paddr else None
    )
    admin_value = (region.admin_dong or region.legal_dong) if region else None

    return Address(
        road=normalize_korean_text(road_value),
        legal=normalize_korean_text(parcel_addr),
        admin=normalize_korean_text(admin_value),
        bjd_code=bjd_code,
        admin_dong_code=admin_dong_code,
        sigungu_code=extract_sigungu_code(bjd_code),
        sido_code=extract_sido_code(bjd_code),
        road_name_code=(paddr.road_name_code if paddr else None),
        zipcode=_five_digits_or_none(paddr.postal_code if paddr else None),
        sido_name=normalize_korean_text(region.sido if region else None),
        sigungu_name=normalize_korean_text(region.sigungu if region else None),
    )


def geocode_response_to_coordinate(
    response: KraddrGeocodeV2Response,
    *,
    min_confidence: float = 0.0,
) -> Coordinate | None:
    """kraddr-geo ``POST /v2/geocode`` 응답 → ``Coordinate`` (WGS84).

    ``status != "OK"`` 이거나 좌표 있는 candidate가 없으면 ``None``.
    ``confidence``가 ``min_confidence`` 미만인 candidate는 제외하고, 남은 것 중
    confidence 최댓값 candidate의 ``point.x/y``를 lon/lat으로.
    """
    if response.status != _STATUS_OK or not response.candidates:
        return None
    usable = [
        c
        for c in response.candidates
        if c.point is not None and c.confidence >= min_confidence
    ]
    if not usable:
        return None
    best = max(usable, key=lambda c: c.confidence)
    point = best.point
    if point is None:  # pragma: no cover — usable 필터로 보장
        return None
    try:
        return Coordinate(lon=Decimal(str(point.x)), lat=Decimal(str(point.y)))
    except (InvalidOperation, ValueError):
        return None


# -- kraddr-geo REST 응답 파싱용 frozen dataclass (Protocol 만족) ---------------


@dataclass(frozen=True)
class _RestPoint:
    x: float
    y: float


@dataclass(frozen=True)
class _RestAddressV2:
    full: str = ""
    road_address: str | None = None
    parcel_address: str | None = None
    postal_code: str | None = None
    legal_dong_code: str | None = None
    admin_dong_code: str | None = None
    road_name: str | None = None
    road_name_code: str | None = None


@dataclass(frozen=True)
class _RestRegionV2:
    bjd_cd: str | None = None
    sido: str | None = None
    sigungu: str | None = None
    legal_dong: str | None = None
    admin_dong: str | None = None


@dataclass(frozen=True)
class _RestCandidateV2:
    confidence: float = 0.0
    match_kind: str = ""
    address: _RestAddressV2 | None = None
    point: _RestPoint | None = None
    distance_m: float | None = None
    region: _RestRegionV2 | None = None


@dataclass(frozen=True)
class _RestReverseV2Response:
    status: str
    candidates: tuple[_RestCandidateV2, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _RestGeocodeV2Response:
    status: str
    candidates: tuple[_RestCandidateV2, ...] = field(default_factory=tuple)


def _parse_point(data: dict[str, Any] | None) -> _RestPoint | None:
    if not data:
        return None
    return _RestPoint(x=float(data["x"]), y=float(data["y"]))


def _parse_address_v2(data: dict[str, Any] | None) -> _RestAddressV2 | None:
    if not data:
        return None
    return _RestAddressV2(
        full=str(data.get("full", "")),
        road_address=data.get("road_address"),
        parcel_address=data.get("parcel_address"),
        postal_code=data.get("postal_code"),
        legal_dong_code=data.get("legal_dong_code"),
        admin_dong_code=data.get("admin_dong_code"),
        road_name=data.get("road_name"),
        road_name_code=data.get("road_name_code"),
    )


def _parse_region_v2(data: dict[str, Any] | None) -> _RestRegionV2 | None:
    if not data:
        return None
    return _RestRegionV2(
        bjd_cd=data.get("bjd_cd"),
        sido=data.get("sido"),
        sigungu=data.get("sigungu"),
        legal_dong=data.get("legal_dong"),
        admin_dong=data.get("admin_dong"),
    )


def _parse_candidate_v2(data: dict[str, Any]) -> _RestCandidateV2:
    return _RestCandidateV2(
        confidence=float(data.get("confidence", 0.0)),
        match_kind=str(data.get("match_kind", "")),
        address=_parse_address_v2(data.get("address")),
        point=_parse_point(data.get("point")),
        distance_m=(
            float(data["distance_m"]) if data.get("distance_m") is not None else None
        ),
        region=_parse_region_v2(data.get("region")),
    )


def _parse_reverse_response(data: dict[str, Any]) -> _RestReverseV2Response:
    cands = tuple(_parse_candidate_v2(c) for c in data.get("candidates", ()))
    return _RestReverseV2Response(
        status=str(data.get("status", "ERROR")), candidates=cands
    )


def _parse_geocode_response(data: dict[str, Any]) -> _RestGeocodeV2Response:
    cands = tuple(_parse_candidate_v2(c) for c in data.get("candidates", ()))
    return _RestGeocodeV2Response(
        status=str(data.get("status", "ERROR")), candidates=cands
    )


# -- kraddr-geo REST 클라이언트 -----------------------------------------------


class KraddrGeoRestClient:
    """kraddr-geo REST API v2 (``POST /v2/{reverse,geocode}``) 비동기 클라이언트.

    ``httpx.AsyncClient``를 주입받아 ``POST /v2/reverse`` / ``POST /v2/geocode``를
    호출하고 JSON을 structural 응답 객체로 파싱한다. 호스트는 주입한
    ``httpx.AsyncClient``의 ``base_url``로 설정 (로컬 개발 예:
    ``httpx.AsyncClient(base_url="http://127.0.0.1:8888")``), 경로 prefix는
    ``base_path`` (기본 ``/v2``). client 수명은 호출자 책임 (ADR-002).
    """

    def __init__(
        self, http_client: httpx.AsyncClient, *, base_path: str = "/v2"
    ) -> None:
        self._http = http_client
        self._base = base_path.rstrip("/")

    async def reverse(
        self,
        x: float,
        y: float,
        *,
        include_region: bool = True,
        include_zipcode: bool = True,
        radius_m: int | None = None,
    ) -> _RestReverseV2Response:
        """``POST /v2/reverse`` — 좌표(x=lon, y=lat) 역지오코딩."""
        body: dict[str, Any] = {
            "lon": x,
            "lat": y,
            "include_region": include_region,
            "include_zipcode": include_zipcode,
        }
        if radius_m is not None:
            body["radius_m"] = radius_m
        resp = await self._http.post(f"{self._base}/reverse", json=body)
        resp.raise_for_status()
        return _parse_reverse_response(resp.json())

    async def geocode(
        self,
        address: str,
        *,
        type_: Literal["road", "parcel"] = "road",
        fallback: Literal["none", "api"] = "none",
    ) -> _RestGeocodeV2Response:
        """``POST /v2/geocode`` — 주소 문자열 정지오코딩.

        ``type_``에 따라 ``road_address``/``jibun_address`` 필드로 보낸다 (v2는
        provider-neutral structured input).
        """
        body: dict[str, Any] = {"fallback": fallback}
        if type_ == "road":
            body["road_address"] = address
        else:
            body["jibun_address"] = address
        resp = await self._http.post(f"{self._base}/geocode", json=body)
        resp.raise_for_status()
        return _parse_geocode_response(resp.json())


# -- kraddr-geo REST client → 콜러블 팩토리 -----------------------------------


def kraddr_geo_reverse_geocoder(
    client: KraddrGeoRestClient,
    *,
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
            float(coord.lon), float(coord.lat), radius_m=radius_m
        )
        return reverse_response_to_address(response, max_distance_m=max_distance_m)

    return _reverse


def kraddr_geo_address_geocoder(
    client: KraddrGeoRestClient,
    *,
    min_confidence: float = 0.0,
    fallback: Literal["none", "api"] = "none",
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
