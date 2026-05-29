"""``krtour.map.geocoding`` — ``python-kraddr-geo`` v2 함수 연동.

좌표 ↔ 행정구역 보강(정/역지오코딩)을 본 라이브러리 ``Address`` / ``Coordinate``
DTO로 정규화한다. geocoding 엔진은 별도 라이브러리 **``python-kraddr-geo``**
(`kraddr.geo.AsyncAddressClient`)가 담당하고, 본 모듈은 그 **v2 응답**(`reverse_v2`
/ `geocode_v2`)을 본 라이브러리 DTO로 옮기는 **순수 변환 함수** + 비동기 콜러블
어댑터만 둔다.

설계 — ADR-006(provider wrapper 금지) 정신 동일
------------------------------------------------
- ``python-kraddr-geo``를 **import 하지 않는다**. kraddr-geo v2 응답
  (`ReverseV2Response`/`GeocodeV2Response`/`CandidateV2`/`RegionV2`/`AddressV2`
  /`Point`)의 **structural Protocol**만 정의하고, 실제 model이 그 shape를
  만족하도록(필드명 일치) 신뢰·미러한다 (ADR-044 — 정합성 1차 책임은 provider).
- 변환 함수(`reverse_v2_to_address`/`geocode_v2_to_coordinate`)는 동기·순수라
  kraddr-geo 없이도 fake 응답으로 단위 테스트된다.
- async 콜러블 팩토리(`kraddr_geo_reverse_geocoder`/`kraddr_geo_address_geocoder`)는
  kraddr-geo client(structural `KraddrGeoClient`)를 받아 ``ReverseGeocoder`` /
  ``AddressGeocoder`` 콜러블을 만든다. client 수명(`open_client`/`close`)은 호출자
  책임 (ADR-002 async-only).

코드 변환 기준은 ``docs/address-geocoding.md §4`` 참조. **철칙**: 주소 문자열만으로
법정동코드 추정 금지 — reverse geocoding 결과(좌표 기반)만 신뢰.

ADR 참조
--------
- ADR-002 — 순수 함수 + async-only client
- ADR-006 — provider 직접 사용 (wrapper class 금지), 구조 Protocol 입력
- ADR-012 — ``Coordinate``는 WGS84 (lon/lat)
- ADR-041 — 주소 DTO/utility는 본 라이브러리 흡수 (kraddr-base)
- ADR-044 — kraddr-geo 데이터 정합성 1차 책임은 kraddr-geo
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from decimal import Decimal, InvalidOperation
from typing import Protocol, runtime_checkable

from krtour.map.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_bjd_code,
    normalize_korean_text,
)
from krtour.map.dto import Address, Coordinate

__all__ = [
    # 비동기 콜러블 계약 (docs/address-geocoding.md §2)
    "AddressGeocoder",
    "ReverseGeocoder",
    "cached_reverse_geocoder",
    # kraddr-geo v2 응답 structural Protocol
    "KraddrPoint",
    "KraddrRegionV2",
    "KraddrAddressV2",
    "KraddrCandidateV2",
    "KraddrReverseV2Response",
    "KraddrGeocodeV2Response",
    "KraddrGeoClient",
    # 순수 변환 함수
    "reverse_v2_to_address",
    "geocode_v2_to_coordinate",
    # kraddr-geo client → 콜러블 팩토리
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


# -- kraddr-geo v2 응답 structural Protocol -----------------------------------
#
# kraddr.geo.dto v2 모델과 필드명 1:1. kraddr-geo를 import하지 않고 구조만 의존.


@runtime_checkable
class KraddrPoint(Protocol):
    """kraddr-geo ``Point`` — ``x=lon`` / ``y=lat`` (WGS84)."""

    @property
    def x(self) -> float: ...
    @property
    def y(self) -> float: ...


@runtime_checkable
class KraddrRegionV2(Protocol):
    """kraddr-geo ``RegionV2`` — 행정구역 코드/명."""

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
class KraddrAddressV2(Protocol):
    """kraddr-geo ``AddressV2`` — 정규화된 주소 + 코드."""

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
class KraddrCandidateV2(Protocol):
    """kraddr-geo ``CandidateV2`` — geocode/reverse 후보 1건."""

    @property
    def confidence(self) -> float: ...
    @property
    def address(self) -> KraddrAddressV2 | None: ...
    @property
    def point(self) -> KraddrPoint | None: ...
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


class KraddrGeoClient(Protocol):
    """kraddr-geo ``AsyncAddressClient``의 v2 메서드 structural shape.

    실제 client는 v2 외 추가 옵션 인자를 더 받지만(있어도 무방), 본 모듈은
    아래 인자만 사용한다.
    """

    async def reverse_v2(
        self,
        lon: float,
        lat: float,
        *,
        radius_m: int | None = None,
    ) -> KraddrReverseV2Response: ...

    async def geocode_v2(
        self,
        *,
        road_address: str | None = None,
        jibun_address: str | None = None,
        sig_cd: str | None = None,
        bjd_cd: str | None = None,
        limit: int = 10,
    ) -> KraddrGeocodeV2Response: ...


# -- 내부 helper --------------------------------------------------------------

_FIVE_DIGITS = re.compile(r"^\d{5}$")
_TEN_DIGITS = re.compile(r"^\d{10}$")
_STATUS_OK = "OK"


def _digits_or_none(value: str | None, pattern: re.Pattern[str]) -> str | None:
    """``value``가 패턴(자릿수)에 맞으면 그대로, 아니면 ``None`` (검증 거부 회피)."""
    if value is None:
        return None
    text = value.strip()
    return text if pattern.match(text) else None


def _best_candidate(
    candidates: tuple[KraddrCandidateV2, ...],
    *,
    min_confidence: float,
    require_point: bool,
) -> KraddrCandidateV2 | None:
    """confidence 최고 후보 (point 필요 시 point 보유 후보 중에서)."""
    best: KraddrCandidateV2 | None = None
    for cand in candidates:
        if require_point and cand.point is None:
            continue
        conf = cand.confidence
        if conf < min_confidence:
            continue
        if best is None or conf > best.confidence:
            best = cand
    return best


# -- 순수 변환 함수 -----------------------------------------------------------


def reverse_v2_to_address(
    response: KraddrReverseV2Response,
    *,
    min_confidence: float = 0.0,
) -> Address | None:
    """kraddr-geo ``reverse_v2`` 응답 → 본 라이브러리 ``Address``.

    ``status != "OK"`` 이거나 (min_confidence 이상) 후보가 없으면 ``None``.
    confidence 최고 후보의 ``region``/``address``를 ``Address``로 옮긴다.

    매핑(``docs/address-geocoding.md §4``)
        - ``bjd_code`` ← ``region.bjd_cd`` (없으면 ``address.legal_dong_code``)
        - ``sigungu_code`` ← ``region.sig_cd`` (없으면 bjd_code에서 파생)
        - ``sido_code`` ← bjd_code에서 파생
        - ``admin_dong_code`` ← ``address.admin_dong_code`` (10자리만)
        - ``road``/``legal`` ← ``address.road_address``/``parcel_address``
        - ``admin`` ← ``region.admin_dong`` 또는 ``eup_myeon_dong`` (한글명)
        - ``zipcode`` ← ``address.postal_code`` (5자리만)
        - ``road_name_code`` ← ``address.road_name_code``
        - ``sido_name``/``sigungu_name`` ← ``region.sido``/``sigungu``

    Notes
    -----
    잘못된 자릿수 코드는 ``None``으로 떨어뜨려 ``Address`` validator 거부를
    피한다. ``building_management_number``(건물관리번호)는 도로명주소 관리번호와
    의미가 달라 매핑하지 않는다.
    """
    if response.status != _STATUS_OK:
        return None
    candidate = _best_candidate(
        response.candidates, min_confidence=min_confidence, require_point=False
    )
    if candidate is None:
        return None

    region = candidate.region
    addr = candidate.address

    bjd_code = normalize_bjd_code(
        (region.bjd_cd if region is not None else None)
        or (addr.legal_dong_code if addr is not None else None)
    )
    sigungu_code = _digits_or_none(
        region.sig_cd if region is not None else None, _FIVE_DIGITS
    ) or extract_sigungu_code(bjd_code)
    sido_code = extract_sido_code(bjd_code)

    admin_name: str | None = None
    if region is not None:
        admin_name = normalize_korean_text(region.admin_dong or region.eup_myeon_dong)

    return Address(
        road=normalize_korean_text(addr.road_address) if addr is not None else None,
        legal=normalize_korean_text(addr.parcel_address) if addr is not None else None,
        admin=admin_name,
        bjd_code=bjd_code,
        admin_dong_code=_digits_or_none(
            addr.admin_dong_code if addr is not None else None, _TEN_DIGITS
        ),
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        road_name_code=(addr.road_name_code if addr is not None else None),
        zipcode=_digits_or_none(
            addr.postal_code if addr is not None else None, _FIVE_DIGITS
        ),
        sido_name=normalize_korean_text(region.sido) if region is not None else None,
        sigungu_name=(
            normalize_korean_text(region.sigungu) if region is not None else None
        ),
    )


def geocode_v2_to_coordinate(
    response: KraddrGeocodeV2Response,
    *,
    min_confidence: float = 0.0,
) -> Coordinate | None:
    """kraddr-geo ``geocode_v2`` 응답 → ``Coordinate`` (WGS84).

    ``status != "OK"`` 이거나 좌표 보유 후보(min_confidence 이상)가 없으면
    ``None``. confidence 최고(point 보유) 후보의 ``point.x/y``를 lon/lat으로.
    """
    if response.status != _STATUS_OK:
        return None
    candidate = _best_candidate(
        response.candidates, min_confidence=min_confidence, require_point=True
    )
    if candidate is None or candidate.point is None:
        return None
    try:
        return Coordinate(
            lon=Decimal(str(candidate.point.x)),
            lat=Decimal(str(candidate.point.y)),
        )
    except (InvalidOperation, ValueError):
        return None


# -- kraddr-geo client → 콜러블 팩토리 ----------------------------------------


def kraddr_geo_reverse_geocoder(
    client: KraddrGeoClient,
    *,
    min_confidence: float = 0.0,
    radius_m: int | None = None,
) -> ReverseGeocoder:
    """kraddr-geo client → ``ReverseGeocoder`` (좌표 → ``Address``) 비동기 콜러블.

    client 수명(`open_client`/`close` 또는 `async with`)은 호출자 책임.

    Examples
    --------
    >>> # from kraddr.geo import open_client
    >>> # async with open_client(pg_dsn=dsn) as client:
    >>> #     reverse = kraddr_geo_reverse_geocoder(client)
    >>> #     addr = await reverse(Coordinate(lon=Decimal("127.0"), lat=Decimal("37.5")))
    """

    async def _reverse(coord: Coordinate) -> Address | None:
        response = await client.reverse_v2(
            lon=float(coord.lon), lat=float(coord.lat), radius_m=radius_m
        )
        return reverse_v2_to_address(response, min_confidence=min_confidence)

    return _reverse


def kraddr_geo_address_geocoder(
    client: KraddrGeoClient,
    *,
    min_confidence: float = 0.0,
) -> AddressGeocoder:
    """kraddr-geo client → ``AddressGeocoder`` (``Address`` → 좌표) 비동기 콜러블.

    ``Address.road``(도로명) → ``road_address``, ``Address.legal``(지번) →
    ``jibun_address``, 행정코드는 ``sig_cd``/``bjd_cd`` 힌트로 전달한다.
    """

    async def _geocode(address: Address) -> Coordinate | None:
        response = await client.geocode_v2(
            road_address=address.road,
            jibun_address=address.legal,
            sig_cd=address.sigungu_code,
            bjd_cd=address.bjd_code,
        )
        return geocode_v2_to_coordinate(response, min_confidence=min_confidence)

    return _geocode
