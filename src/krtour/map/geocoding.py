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
- 변환 함수(``reverse_response_to_address``/``geocode_response_to_coordinate``/
  ``geocode_response_to_address``)는
  동기·순수라 ``kraddr-geo``/HTTP 없이 fake 응답으로 단위 테스트된다.
- async 콜러블 팩토리(``kraddr_geo_reverse_geocoder``/``kraddr_geo_address_geocoder``)는
  ``KraddrGeoRestClient``를 받아 ``ReverseGeocoder`` / ``AddressGeocoder`` 콜러블을
  만든다. ``httpx.AsyncClient`` 수명(base_url 설정/close)은 호출자 책임 (ADR-002).

**철칙**: 주소 문자열을 직접 파싱해 법정동코드를 추정하지 않는다. 법정동코드는
kraddr-geo v2가 반환한 structured ``legal_dong_code``/``region.bjd_cd``만 신뢰한다.

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
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol, cast, runtime_checkable

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
    "AddressResolver",
    "ReverseGeocoder",
    "cached_address_resolver",
    "cached_reverse_geocoder",
    # kraddr-geo REST v2 응답 structural Protocol
    "KraddrPoint",
    "KraddrAddressV2",
    "KraddrRegionV2",
    "KraddrCandidateV2",
    "KraddrReverseV2Response",
    "KraddrGeocodeV2Response",
    "RegionWithinRadiusCenter",
    "RegionWithinRadiusItem",
    "RegionWithinRadiusLevel",
    "RegionWithinRadiusRelation",
    "RegionsWithinRadiusResponse",
    # 순수 변환 함수
    "reverse_response_to_address",
    "geocode_response_to_address",
    "geocode_response_to_coordinate",
    # REST client + 콜러블 팩토리
    "KraddrGeoRestClient",
    "kraddr_geo_reverse_geocoder",
    "kraddr_geo_address_geocoder",
    "kraddr_geo_address_resolver",
    "resolve_regions_within_radius",
    "resolve_sigungu_by_radius",
]


# -- 비동기 콜러블 계약 --------------------------------------------------------
#
# docs/address-geocoding.md §2. provider 적재 파이프라인이 받는 enrichment
# resource — async-only (ADR-002). standard_data.ReverseGeocoder(동기 Protocol)와
# 구분된다 (그쪽은 sync lookup table용).

AddressGeocoder = Callable[[Address], Awaitable[Coordinate | None]]
"""정지오코딩: ``Address`` → ``Coordinate | None`` (await)."""

AddressResolver = Callable[[Address], Awaitable[Address | None]]
"""주소 보강: ``Address`` → 행정코드가 채워진 ``Address | None`` (await)."""

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


def cached_address_resolver(resolver: AddressResolver) -> AddressResolver:
    """``AddressResolver``를 표시 주소 문자열 기준으로 메모이즈한다.

    CSV/TSV나 provider batch에는 같은 도로명/지번 주소가 반복될 수 있다. ``None``
    결과도 캐시해 같은 실패 주소를 반복 호출하지 않는다.
    """
    cache: dict[str, Address | None] = {}

    async def _cached(address: Address) -> Address | None:
        key = (address.road or address.legal or address.admin or "").strip()
        if not key:
            return None
        if key not in cache:
            cache[key] = await resolver(address)
        return cache[key]

    return _cached


# -- kraddr-geo REST v2 응답 structural Protocol ------------------------------
#
# kraddr.geo.dto.v2 모델과 필드명 1:1 (kraddr-geo를 import하지 않고 구조만 의존).
# CandidateV2.address.legal_dong_code(10) / admin_dong_code(10) / road_name_code /
# region.sig_cd / region.bjd_cd / region.sido / region.sigungu
# (kraddr.geo.dto.v2 참조).


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
    def sig_cd(self) -> str | None: ...
    @property
    def bjd_cd(self) -> str | None: ...
    @property
    def sido(self) -> str | None: ...
    @property
    def sigungu(self) -> str | None: ...
    @property
    def eup_myeon_dong(self) -> str | None: ...
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

RegionWithinRadiusLevel = Literal["sido", "sigungu", "emd"]
"""kraddr-geo v2 ``RegionsWithinRadiusInput.levels`` 값."""

RegionWithinRadiusRelation = Literal["contains", "overlaps"]
"""kraddr-geo v2 반경 행정구역 관계. 중심 포함=contains, 반경 교차=overlaps."""

_VALID_REGION_RELATIONS: Final[frozenset[str]] = frozenset(("contains", "overlaps"))


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


def _two_digits_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text if (len(text) == 2 and text.isdigit()) else None


@dataclass(frozen=True)
class RegionWithinRadiusCenter:
    """kraddr-geo v2 반경 행정구역 질의 중심점. 외부 순서는 ``(lon, lat)``."""

    lon: float
    lat: float


@dataclass(frozen=True)
class RegionWithinRadiusItem:
    """kraddr-geo v2 반경 안에 포함/교차하는 행정구역."""

    code: str
    name: str | None
    relation: RegionWithinRadiusRelation


@dataclass(frozen=True)
class RegionsWithinRadiusResponse:
    """kraddr-geo v2 ``POST /v2/regions/within-radius`` 응답."""

    center: RegionWithinRadiusCenter
    radius_km: float
    sido: tuple[RegionWithinRadiusItem, ...] = ()
    sigungu: tuple[RegionWithinRadiusItem, ...] = ()
    emd: tuple[RegionWithinRadiusItem, ...] = ()


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
        - ``sigungu_code`` / ``sido_code`` ← bjd_code에서 파생. bjd가 없으면
          ``region.sig_cd``에서 보존
        - ``road`` ← road candidate ``address.road_address`` (없으면 ``address.full``)
        - ``legal`` ← parcel candidate ``address.parcel_address``
        - ``admin`` ← ``region.admin_dong`` 또는 ``region.legal_dong`` 또는
          ``region.eup_myeon_dong``
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
    region_sigungu_code = _five_digits_or_none(region.sig_cd if region else None)
    sigungu_code = extract_sigungu_code(bjd_code) or region_sigungu_code
    sido_code = extract_sido_code(bjd_code) or _two_digits_or_none(
        sigungu_code[:2] if sigungu_code else None
    )
    admin_value = (
        (region.admin_dong or region.legal_dong or region.eup_myeon_dong)
        if region
        else None
    )

    return Address(
        road=normalize_korean_text(road_value),
        legal=normalize_korean_text(parcel_addr),
        admin=normalize_korean_text(admin_value),
        bjd_code=bjd_code,
        admin_dong_code=admin_dong_code,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
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


def geocode_response_to_address(
    response: KraddrGeocodeV2Response,
    *,
    min_confidence: float = 0.0,
) -> Address | None:
    """kraddr-geo ``POST /v2/geocode`` 응답 → 행정코드 보강 ``Address``.

    주소 문자열을 파싱하지 않고, confidence 필터를 통과한 최상위 candidate의
    structured ``address.legal_dong_code``/``region.bjd_cd``만 사용한다. 좌표만
    필요하면 ``geocode_response_to_coordinate``를 사용한다.
    """
    if response.status != _STATUS_OK or not response.candidates:
        return None
    usable = [
        c
        for c in response.candidates
        if c.address is not None and c.confidence >= min_confidence
    ]
    if not usable:
        return None
    best = max(usable, key=lambda c: c.confidence)
    addr = best.address
    region = best.region
    if addr is None:  # pragma: no cover — usable 필터로 보장
        return None

    raw_bjd = addr.legal_dong_code or (region.bjd_cd if region else None)
    try:
        bjd_code = normalize_bjd_code(raw_bjd)
    except ValueError:
        bjd_code = None

    admin_dong_code = addr.admin_dong_code
    if admin_dong_code is not None and not (
        len(admin_dong_code) == 10 and admin_dong_code.isdigit()
    ):
        admin_dong_code = None

    region_sigungu_code = _five_digits_or_none(region.sig_cd if region else None)
    sigungu_code = extract_sigungu_code(bjd_code) or region_sigungu_code
    sido_code = extract_sido_code(bjd_code) or _two_digits_or_none(
        sigungu_code[:2] if sigungu_code else None
    )
    admin_value = (
        (region.admin_dong or region.legal_dong or region.eup_myeon_dong)
        if region
        else None
    )
    return Address(
        road=normalize_korean_text(addr.road_address or addr.full),
        legal=normalize_korean_text(addr.parcel_address),
        admin=normalize_korean_text(admin_value),
        bjd_code=bjd_code,
        admin_dong_code=admin_dong_code,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        road_name_code=addr.road_name_code,
        zipcode=_five_digits_or_none(addr.postal_code),
        sido_name=normalize_korean_text(region.sido if region else None),
        sigungu_name=normalize_korean_text(region.sigungu if region else None),
    )


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
    sig_cd: str | None = None
    bjd_cd: str | None = None
    sido: str | None = None
    sigungu: str | None = None
    eup_myeon_dong: str | None = None
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
        sig_cd=data.get("sig_cd"),
        bjd_cd=data.get("bjd_cd"),
        sido=data.get("sido"),
        sigungu=data.get("sigungu"),
        eup_myeon_dong=data.get("eup_myeon_dong"),
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


def _parse_region_center(data: dict[str, Any]) -> RegionWithinRadiusCenter:
    raw = data.get("center")
    if not isinstance(raw, dict):
        raise ValueError("kraddr-geo regions response center must be an object")
    lon_raw = raw.get("lon", raw.get("x"))
    lat_raw = raw.get("lat", raw.get("y"))
    if lon_raw is None or lat_raw is None:
        raise ValueError("kraddr-geo regions response center has invalid lon/lat")
    try:
        return RegionWithinRadiusCenter(lon=float(lon_raw), lat=float(lat_raw))
    except (TypeError, ValueError) as exc:
        raise ValueError("kraddr-geo regions response center has invalid lon/lat") from exc


def _parse_region_item(data: object) -> RegionWithinRadiusItem | None:
    if not isinstance(data, dict):
        return None
    code = str(data.get("code", "")).strip()
    if not code:
        return None
    raw_relation = str(data.get("relation", "")).strip()
    if raw_relation not in _VALID_REGION_RELATIONS:
        return None
    name_raw = data.get("name")
    name = str(name_raw).strip() if name_raw is not None else None
    return RegionWithinRadiusItem(
        code=code,
        name=name or None,
        relation=cast("RegionWithinRadiusRelation", raw_relation),
    )


def _parse_region_items(data: dict[str, Any], key: str) -> tuple[RegionWithinRadiusItem, ...]:
    raw_items = data.get(key, ())
    if not isinstance(raw_items, list | tuple):
        return ()
    return tuple(item for raw in raw_items if (item := _parse_region_item(raw)) is not None)


def _parse_regions_within_radius_response(data: dict[str, Any]) -> RegionsWithinRadiusResponse:
    center = _parse_region_center(data)
    try:
        radius_km = float(data["radius_km"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("kraddr-geo regions response radius_km is invalid") from exc
    if radius_km <= 0:
        raise ValueError("kraddr-geo regions response radius_km must be positive")
    return RegionsWithinRadiusResponse(
        center=center,
        radius_km=radius_km,
        sido=_parse_region_items(data, "sido"),
        sigungu=_parse_region_items(data, "sigungu"),
        emd=_parse_region_items(data, "emd"),
    )


# -- kraddr-geo REST 클라이언트 -----------------------------------------------


class KraddrGeoRestClient:
    """kraddr-geo REST API v2 (``POST /v2/{reverse,geocode}``) 비동기 클라이언트.

    ``httpx.AsyncClient``를 주입받아 ``POST /v2/reverse`` / ``POST /v2/geocode``를
    호출하고 JSON을 structural 응답 객체로 파싱한다. 호스트는 주입한
    ``httpx.AsyncClient``의 ``base_url``로 설정 (로컬 개발 예:
    ``httpx.AsyncClient(base_url="http://127.0.0.1:9001")``), 경로 prefix는
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

    async def regions_within_radius(
        self,
        *,
        lon: float,
        lat: float,
        radius_km: float = 3.0,
        levels: tuple[RegionWithinRadiusLevel, ...] = ("sigungu", "emd"),
    ) -> RegionsWithinRadiusResponse:
        """``POST /v2/regions/within-radius`` — 반경 안 행정구역 조회."""
        body: dict[str, Any] = {
            "lon": lon,
            "lat": lat,
            "radius_km": radius_km,
            "levels": list(levels),
        }
        resp = await self._http.post(f"{self._base}/regions/within-radius", json=body)
        resp.raise_for_status()
        return _parse_regions_within_radius_response(resp.json())


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
    >>> # async with httpx.AsyncClient(base_url="http://127.0.0.1:9001") as http:
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


def kraddr_geo_address_resolver(
    client: KraddrGeoRestClient,
    *,
    min_confidence: float = 0.0,
    fallback: Literal["none", "api"] = "none",
) -> AddressResolver:
    """kraddr-geo REST client → ``AddressResolver`` (주소 → 행정코드 보강) 콜러블.

    ``Address.road``가 있으면 road geocode를 먼저 시도하고, ``Address.legal``이
    있으면 parcel geocode를 fallback으로 시도한다. 둘 다 없으면 ``None``.
    """

    async def _resolve(address: Address) -> Address | None:
        queries: list[tuple[str, Literal["road", "parcel"]]] = []
        if address.road:
            queries.append((address.road, "road"))
        if address.legal and address.legal != address.road:
            queries.append((address.legal, "parcel"))
        if not queries:
            return None
        for query, addr_type in queries:
            response = await client.geocode(query, type_=addr_type, fallback=fallback)
            resolved = geocode_response_to_address(
                response, min_confidence=min_confidence
            )
            if resolved is not None and resolved.bjd_code is not None:
                return resolved
        return None

    return _resolve


async def resolve_regions_within_radius(
    client: KraddrGeoRestClient,
    *,
    lon: float,
    lat: float,
    radius_km: float,
    levels: tuple[RegionWithinRadiusLevel, ...] = ("sigungu", "emd"),
) -> RegionsWithinRadiusResponse:
    """kraddr-geo REST v2로 POI 반경 행정구역을 조회한다."""
    return await client.regions_within_radius(
        lon=lon,
        lat=lat,
        radius_km=radius_km,
        levels=levels,
    )


async def resolve_sigungu_by_radius(
    client: KraddrGeoRestClient,
    *,
    lon: float,
    lat: float,
    radius_km: float,
) -> tuple[str, ...]:
    """``sigungu_by_radius`` scope resolver용 시군구 코드 목록."""
    response = await resolve_regions_within_radius(
        client,
        lon=lon,
        lat=lat,
        radius_km=radius_km,
        levels=("sigungu",),
    )
    return tuple(item.code for item in response.sigungu)
