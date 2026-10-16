"""``kortravelmap.geocoding`` — ``kor-travel-geo`` **REST API v2** 연동.

좌표 ↔ 행정구역 보강(정/역지오코딩)을 본 라이브러리 ``Address`` / ``Coordinate``
DTO로 정규화한다. geocoding 엔진은 별도 서비스 **``kor-travel-geo``** (FastAPI,
provider-neutral ``POST /v2/{reverse,geocode}``)가 담당하고, 본 모듈은 그 **REST
응답**(``ReverseV2Response`` / ``GeocodeV2Response``)을 본 라이브러리 DTO로 옮기는
**순수 변환 함수** + HTTP 클라이언트 + 비동기 콜러블 어댑터만 둔다.

v2 (provider-neutral) 전환
--------------------------
이전 구현은 kor-travel-geo ``GET /v1/address/{reverse,geocode}``(JUSO 호환,
``structure.level4LC`` 파싱)를 호출했으나, 현재 정본은 **``POST /v2/*``**
(``CandidateV2.address.legal_dong_code`` 등 **structured field 직접 제공** +
``CandidateV2.point = {lon, lat}`` + ``confidence``/``distance_m``/
``match_kind``)다. v2는 vworld level 파싱 없이
법정동코드를 바로 받으므로 본 모듈은 v2로 전환한다 (kor-travel-geo
``src/kortravelgeo/dto/v2.py`` 정합).

설계 — ADR-006(provider wrapper 금지) 정신 동일
------------------------------------------------
- ``kor-travel-geo`` / ``httpx``를 **런타임 import 하지 않는다**. REST 응답
  (``ReverseV2Response``/``GeocodeV2Response``/``CandidateV2``/``AddressV2``/
  ``RegionV2``/``PointV2``)의 **structural Protocol**만 정의하고, 호출 측이 주입한
  ``httpx.AsyncClient``로 HTTP를 친다 (ADR-044 — 정합성 1차 책임은 kor-travel-geo).
- 변환 함수(``reverse_response_to_address``/``geocode_response_to_coordinate``/
  ``geocode_response_to_address``)는
  동기·순수라 ``kor-travel-geo``/HTTP 없이 fake 응답으로 단위 테스트된다.
- async 콜러블 팩토리(``kor_travel_geo_reverse_geocoder``/``kor_travel_geo_address_geocoder``)는
  ``KorTravelGeoRestClient``를 받아 ``ReverseGeocoder`` / ``AddressGeocoder`` 콜러블을
  만든다. ``httpx.AsyncClient`` 수명(base_url 설정/close)은 호출자 책임 (ADR-002).

**철칙**: 주소 문자열을 직접 파싱해 법정동코드를 추정하지 않는다. 법정동코드는
kor-travel-geo v2가 반환한 structured ``legal_dong_code``/``region.bjd_cd``만 신뢰한다.

ADR 참조
--------
- ADR-002 — 순수 함수 + async-only client
- ADR-006 — provider 직접 사용 (wrapper class 금지), 구조 Protocol 입력 + client 주입
- ADR-012 — ``Coordinate``는 WGS84 (lon/lat)
- ADR-041 — 주소 DTO/utility는 본 라이브러리 흡수 (kraddr-base)
- ADR-044 — kor-travel-geo 데이터 정합성 1차 책임은 kor-travel-geo (REST 응답 신뢰·미러)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from collections import Counter, OrderedDict, deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import (
    TYPE_CHECKING,
    Any,
    Final,
    Literal,
    Protocol,
    TypeVar,
    cast,
    runtime_checkable,
)

from pydantic import SecretStr

from kortravelmap.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_bjd_code,
    normalize_korean_text,
)
from kortravelmap.core.exceptions import GeoAuthNotConfiguredError, GeoRequestError
from kortravelmap.dto import Address, Coordinate
from kortravelmap.dto.geo_dataset import DatasetRef

if TYPE_CHECKING:
    import httpx

    from kortravelmap.settings import KorTravelMapSettings

_GeoResponseT = TypeVar("_GeoResponseT")


def geo_http_timeout(settings: KorTravelMapSettings) -> httpx.Timeout:
    """kor-travel-geo client의 ``httpx.Timeout`` — 모든 geo client 생성 지점이 쓴다(ADR-110 결정 3).

    첫 위치 인자(``kor_travel_geo_timeout_seconds``)가 read·write·pool을 덮고, 연결 수립만
    ``kor_travel_geo_connect_timeout_seconds``로 따로 둔다. geo가 다른 호스트(odroid)에 있어
    그 호스트가 꺼지면 연결은 거부(RST)가 아니라 무응답이 되므로, 분리하지 않으면 호출마다
    read 상한(기본 10 s)까지 기다린다. ``httpx.Timeout(connect=…, read=…)``처럼 둘만 주면
    httpx 0.28이 ``ValueError``로 거부하므로 그 꼴은 쓰지 않는다.
    ``tests/lint/test_geo_transport_clients_use_timeout_factory.py``가 생성 지점마다 이
    호출을 강제한다. httpx는 TYPE_CHECKING-only 규약(``pyproject.toml``)이라 지역 import다.
    """
    import httpx as _httpx

    return _httpx.Timeout(
        settings.kor_travel_geo_timeout_seconds,
        connect=settings.kor_travel_geo_connect_timeout_seconds,
    )


def _is_public_key_rejection(resp: httpx.Response) -> bool:
    """geo가 Map의 public API key를 거부했는지 판정한다."""
    if resp.status_code not in {400, 401}:
        return False
    try:
        payload = resp.json()
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    error = payload.get("error")
    if not isinstance(error, dict):
        return False
    return (
        resp.status_code == 400
        and error.get("code") == "E0100"
        and error.get("field") == "key"
    ) or (resp.status_code == 401 and error.get("code") == "E0401")


def _raise_for_status_sanitized(resp: httpx.Response) -> None:
    """HTTP status 오류를 credential 없는 typed 예외로 바꾼다."""
    import httpx as _httpx

    if _is_public_key_rejection(resp):
        raise GeoAuthNotConfiguredError(
            "kor-travel-geo가 Map public API key를 거부했습니다. "
            "KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY와 geo의 public key 설정을 확인하세요."
        )

    sanitized: GeoRequestError | None = None
    try:
        resp.raise_for_status()
    except _httpx.HTTPStatusError as exc:
        sanitized = GeoRequestError(
            f"kor-travel-geo 호출 실패: {exc.response.status_code} "
            f"{exc.response.reason_phrase}"
        )
    # except 블록 **밖에서** 던진다. 안에서 던지면 ``from None``으로도 ``__context__``에
    # 원본(=key가 든 URL 문자열)이 남아, ``__context__``를 따라가는 로거·리포터로 샌다.
    if sanitized is not None:
        raise sanitized


def _parse_response_payload(
    resp: httpx.Response,
    parser: Callable[[dict[str, Any]], _GeoResponseT],
) -> _GeoResponseT:
    """Raw provider payload를 짧은 내부 frame 안에서만 파싱한다."""
    payload = resp.json()
    if not isinstance(payload, dict):
        raise TypeError("response JSON is not an object")
    return parser(payload)


def _parse_response_sanitized(
    resp: httpx.Response,
    parser: Callable[[dict[str, Any]], _GeoResponseT],
) -> _GeoResponseT:
    """2xx JSON/schema 손상을 raw payload 없는 typed provider 오류로 바꾼다."""
    error_type: str | None = None
    try:
        return _parse_response_payload(resp, parser)
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError) as exc:
        error_type = type(exc).__name__
    # 원 JSON decoder/parser 예외의 frame local에 raw payload가 남을 수 있으므로
    # except 블록 밖에서 새 typed 오류를 던져 exception chaining도 만들지 않는다.
    assert error_type is not None
    raise GeoRequestError(f"kor-travel-geo 응답 계약 오류: {error_type}")


__all__ = [
    # 비동기 콜러블 계약 (docs/architecture/address-geocoding.md §2)
    "AddressGeocoder",
    "AddressResolver",
    "ObservedReverseGeocoder",
    "PrefetchingReverseGeocoder",
    "ReverseGeocodeObservation",
    "ReverseGeocoder",
    "cached_address_resolver",
    "cached_reverse_geocoder",
    # kor-travel-geo REST v2 응답 structural Protocol
    "KraddrPoint",
    "KraddrAddressV2",
    "KraddrRegionV2",
    "KraddrCandidateV2",
    "KraddrReverseV2Response",
    "KorTravelGeocodeV2Response",
    "RegionWithinRadiusCenter",
    "RegionWithinRadiusItem",
    "RegionWithinRadiusLevel",
    "RegionWithinRadiusRelation",
    "RegionsWithinRadiusResponse",
    # 순수 변환 함수
    "reverse_response_to_address",
    "geocode_response_to_address",
    "geocode_response_to_coordinate",
    # 경계 계측
    "GeoCallStats",
    # REST client + 콜러블 팩토리
    "KorTravelGeoRestClient",
    "REVERSE_RESULT_EMPTY_KEY",
    "fetch_current_dataset",
    "open_geo_client",
    "geo_dataset_mismatch",
    "geo_http_timeout",
    "kor_travel_geo_reverse_geocoder",
    "kor_travel_geo_address_geocoder",
    "kor_travel_geo_address_resolver",
    "resolve_regions_within_radius",
    "resolve_sigungu_by_radius",
]


# -- 비동기 콜러블 계약 --------------------------------------------------------
#
# docs/architecture/address-geocoding.md §2. provider 적재 파이프라인이 받는 enrichment
# resource — async-only (ADR-002). standard_data.ReverseGeocoder(동기 Protocol)와
# 구분된다 (그쪽은 sync lookup table용).

AddressGeocoder = Callable[[Address], Awaitable[Coordinate | None]]
"""정지오코딩: ``Address`` → ``Coordinate | None`` (await)."""

AddressResolver = Callable[[Address], Awaitable[Address | None]]
"""주소 보강: ``Address`` → 행정코드가 채워진 ``Address | None`` (await)."""

ReverseGeocoder = Callable[[Coordinate], Awaitable[Address | None]]
"""역지오코딩: ``Coordinate`` → ``Address | None`` (await)."""


@dataclass(frozen=True)
class ReverseGeocodeObservation:
    """대표 주소와 reverse 후보 전체의 시군구명을 함께 보존한 관측."""

    address: Address | None
    sigungu_names: tuple[str, ...] = ()


@runtime_checkable
class ObservedReverseGeocoder(Protocol):
    """대표 주소 외에 후보집합 증거도 제공하는 ``ReverseGeocoder``."""

    async def __call__(self, coord: Coordinate) -> Address | None: ...

    async def observe(self, coord: Coordinate) -> ReverseGeocodeObservation: ...


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
) -> ObservedReverseGeocoder:
    """``ReverseGeocoder``를 좌표(precision 자리 양자화) 기준 메모이즈한다.

    반환 콜러블은 호출 수명 동안 결과(``Address | None`` 포함)를 캐싱 — batch
    변환에서 중복 좌표의 역지오코딩 round-trip을 1회로 줄인다. ``None`` 결과도
    캐싱하므로 실패 좌표를 재시도하지 않는다.
    """
    return _CachedObservedReverseGeocoder(geocoder, precision=precision)


class _CachedObservedReverseGeocoder:
    def __init__(self, geocoder: ReverseGeocoder, *, precision: int) -> None:
        self._geocoder = geocoder
        self._precision = precision
        self._cache: dict[tuple[str, str], ReverseGeocodeObservation] = {}

    def _key(self, coord: Coordinate) -> tuple[str, str]:
        return (
            f"{coord.lon:.{self._precision}f}",
            f"{coord.lat:.{self._precision}f}",
        )

    async def observe(self, coord: Coordinate) -> ReverseGeocodeObservation:
        key = self._key(coord)
        if key not in self._cache:
            if isinstance(self._geocoder, ObservedReverseGeocoder):
                observation = await self._geocoder.observe(coord)
            else:
                address = await self._geocoder(coord)
                names = (
                    (address.sigungu_name,)
                    if address is not None and address.sigungu_name
                    else ()
                )
                observation = ReverseGeocodeObservation(address, names)
            self._cache[key] = observation
        return self._cache[key]

    async def __call__(self, coord: Coordinate) -> Address | None:
        return (await self.observe(coord)).address


class PrefetchingReverseGeocoder:
    """run 수명의 bounded LRU 캐시 + bounded 동시성 선조회를 갖는 역지오코더 (ADR-108).

    ``cached_reverse_geocoder``는 변환 호출 **한 번** 동안만 살고 좌표를 하나씩 순서대로
    부른다. 수십만 건 적재에서는 두 가지가 모자라다 — chunk를 넘어 같은 건물 좌표가
    반복되고, kor-travel-geo는 batch endpoint가 없어 왕복 지연이 그대로 누적된다.

    그래서 적재기가 chunk의 좌표를 먼저 모아 :meth:`prefetch`로 **최대
    ``concurrency``개까지 동시에** 조회해 캐시에 채운다. 그 뒤 변환 함수가 평소처럼
    좌표를 하나씩 부르면 캐시에서 바로 나온다. 동시성 상한은 geo의 용량을 지키는
    유일한 손잡이이므로 보수적으로 둔다(호출자가 settings에서 읽는다).

    - 결과가 ``None``인 좌표도 캐시한다(``cached_reverse_geocoder``와 같다).
    - 선조회에서 **예외**가 난 좌표는 캐시하지 않는다. 변환이 그 좌표를 다시 부를 때 한 번
      더 실시간으로 시도하고, 그래도 실패하면 예외가 그대로 올라간다 — 실패를 ``None``으로
      삼키면 bjd가 빈 feature가 조용히 적재된다.
    - 캐시는 ``max_entries``에서 가장 오래 안 쓴 항목부터 버린다(메모리 상한).
    """

    def __init__(
        self,
        geocoder: ReverseGeocoder,
        *,
        concurrency: int,
        max_entries: int = 50_000,
        precision: int = _DEFAULT_COORD_PRECISION,
        recent_window: int = 50,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._geocoder = geocoder
        self._concurrency = concurrency
        self._max_entries = max_entries
        self._precision = precision
        self._cache: OrderedDict[tuple[str, str], ReverseGeocodeObservation] = OrderedDict()
        self.live_calls = 0
        """upstream으로 실제로 나간 조회 수(선조회 + 캐시 미스)."""
        self.cache_hits = 0
        """캐시에서 바로 답한 조회 수(선조회 단계의 중복 제거 포함)."""
        self.prefetch_failures = 0
        """선조회에서 예외가 나 캐시하지 않은 좌표 수."""
        self.empty_results = 0
        """upstream이 답은 했지만 법정동코드를 내지 못한 조회 수."""
        self._recent_empty: deque[bool] = deque(maxlen=recent_window)
        self.last_good_coord: Coordinate | None = None
        """이 run에서 마지막으로 법정동코드를 받아 온 좌표(장애 판정 probe의 1순위)."""
        self.probes = 0
        """:meth:`probe_healthy` 호출 수."""
        self.probe_passes = 0
        """:meth:`probe_healthy`가 건강하다고 판정한 수."""

    async def _resolves(self, coord: Coordinate) -> bool:
        if isinstance(self._geocoder, ObservedReverseGeocoder):
            address = (await self._geocoder.observe(coord)).address
        else:
            address = await self._geocoder(coord)
        return address is not None and address.bjd_code is not None

    async def probe_healthy(self, reference: Coordinate) -> bool:
        """캐시를 거치지 않고 알려진 좋은 좌표를 다시 물어 geo가 살아 있는지 본다.

        최근 창의 빈 답 비율만으로는 "geo 장애"와 "빈 답이 정상인 좌표(바다·경계)만 남은
        재개 run"을 가를 수 없다. 고정 기준 좌표 ``reference``와 이 run에서 법정동코드를 받아 온
        마지막 좌표를 **둘 다** 묻고, 둘 다 답하면 건강하다 — 최근 창을 비워 다음 판정이 새
        표본으로 시작하게 한다. 하나라도 빈 답이면 ``False``. 예외는 그대로 올라간다(그것도
        장애다). 이 조회는 통계 창에 넣지 않는다.

        probe가 통과해도 **지역** 장애(한 시·도 layer만 빈 경우)는 가리지 못한다 — 호출자가 같은
        업종에서 통과한 판정이 거듭되는지와 빈 답 비율 상한으로 따로 본다.
        """
        self.probes += 1
        coords = [reference]
        if self.last_good_coord is not None and self.last_good_coord != reference:
            coords.append(self.last_good_coord)
        for coord in coords:
            if not await self._resolves(coord):
                return False
        self.probe_passes += 1
        self._recent_empty.clear()
        return True

    @property
    def recent_lookups(self) -> int:
        """최근 창(``recent_window``)에 든 upstream 조회 수."""
        return len(self._recent_empty)

    @property
    def recent_empty_ratio(self) -> float:
        """최근 창에서 법정동코드 없이 돌아온 조회의 비율. 조회가 없으면 0.

        좌표 하나가 빈 답을 받는 것은 정상(바다·경계)이지만, 연속 대부분이 빈 답이면
        geo가 사실상 죽은 것이다. 호출자가 이것으로 "행 단위 실패"와 "upstream 장애"를
        가른다.
        """
        if not self._recent_empty:
            return 0.0
        return sum(self._recent_empty) / len(self._recent_empty)

    def _key(self, coord: Coordinate) -> tuple[str, str]:
        return (
            f"{coord.lon:.{self._precision}f}",
            f"{coord.lat:.{self._precision}f}",
        )

    def _remember(self, key: tuple[str, str], observation: ReverseGeocodeObservation) -> None:
        self._cache[key] = observation
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)

    async def _lookup(self, coord: Coordinate) -> ReverseGeocodeObservation:
        self.live_calls += 1
        if isinstance(self._geocoder, ObservedReverseGeocoder):
            observation = await self._geocoder.observe(coord)
        else:
            address = await self._geocoder(coord)
            names = (
                (address.sigungu_name,) if address is not None and address.sigungu_name else ()
            )
            observation = ReverseGeocodeObservation(address, names)
        empty = observation.address is None or observation.address.bjd_code is None
        self.empty_results += int(empty)
        self._recent_empty.append(empty)
        if not empty:
            self.last_good_coord = coord
        return observation

    async def prefetch(self, coords: Iterable[Coordinate]) -> int:
        """캐시에 없는 좌표를 중복 없이 최대 ``concurrency``개씩 동시에 조회한다.

        반환값은 이번에 upstream으로 보낸 조회 수다.
        """
        pending: dict[tuple[str, str], Coordinate] = {}
        for coord in coords:
            key = self._key(coord)
            if key in self._cache:
                self._cache.move_to_end(key)
                self.cache_hits += 1
            elif key in pending:
                self.cache_hits += 1
            else:
                pending[key] = coord
        if not pending:
            return 0
        gate = asyncio.Semaphore(self._concurrency)

        async def _one(key: tuple[str, str], coord: Coordinate) -> None:
            async with gate:
                try:
                    observation = await self._lookup(coord)
                except Exception:  # noqa: BLE001 — 캐시하지 않고 변환의 실시간 재시도에 맡긴다
                    self.prefetch_failures += 1
                    return
            self._remember(key, observation)

        await asyncio.gather(*(_one(key, coord) for key, coord in pending.items()))
        return len(pending)

    async def observe(self, coord: Coordinate) -> ReverseGeocodeObservation:
        key = self._key(coord)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            self.cache_hits += 1
            return cached
        observation = await self._lookup(coord)
        self._remember(key, observation)
        return observation

    async def __call__(self, coord: Coordinate) -> Address | None:
        return (await self.observe(coord)).address


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


# -- kor-travel-geo REST v2 응답 structural Protocol ------------------------------
#
# kraddr.geo.dto.v2 모델과 필드명 1:1 (kor-travel-geo를 import하지 않고 구조만 의존).
# CandidateV2.address.legal_dong_code(10) / admin_dong_code(10) / road_name_code /
# region.sig_cd / region.bjd_cd / region.sido / region.sigungu
# (kraddr.geo.dto.v2 참조).


@runtime_checkable
class KraddrPoint(Protocol):
    """kor-travel-geo ``PointV2`` — ``lon`` / ``lat`` (WGS84)."""

    @property
    def lon(self) -> float: ...
    @property
    def lat(self) -> float: ...


@runtime_checkable
class KraddrAddressV2(Protocol):
    """kor-travel-geo ``AddressV2`` — structured 주소 (코드 직접 제공)."""

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
    """kor-travel-geo ``RegionV2`` — 행정구역 명칭/코드."""

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
    """kor-travel-geo ``CandidateV2`` — reverse/geocode 결과 1건."""

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
    """kor-travel-geo ``ReverseV2Response``."""

    @property
    def status(self) -> str: ...
    @property
    def candidates(self) -> tuple[KraddrCandidateV2, ...]: ...


@runtime_checkable
class KorTravelGeocodeV2Response(Protocol):
    """kor-travel-geo ``GeocodeV2Response``."""

    @property
    def status(self) -> str: ...
    @property
    def candidates(self) -> tuple[KraddrCandidateV2, ...]: ...


# -- 내부 helper --------------------------------------------------------------

_STATUS_OK = "OK"
_TYPE_ROAD = "road"
_TYPE_PARCEL = "parcel"

RegionWithinRadiusLevel = Literal["sido", "sigungu", "emd"]
"""kor-travel-geo v2 ``RegionsWithinRadiusInput.levels`` 값."""

RegionWithinRadiusRelation = Literal["contains", "overlaps"]
"""kor-travel-geo v2 반경 행정구역 관계. 중심 포함=contains, 반경 교차=overlaps."""

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


def _contains_region_item(
    items: tuple[RegionWithinRadiusItem, ...],
) -> RegionWithinRadiusItem | None:
    return next((item for item in items if item.relation == "contains"), None)


def _bjd_code_from_emd_code(value: str | None) -> str | None:
    if value is None:
        return None
    code = value.strip()
    if len(code) == 8 and code.isdigit():
        code = f"{code}00"
    try:
        return normalize_bjd_code(code)
    except ValueError:
        return None


def _region_names(*values: str | None) -> str | None:
    text = " ".join(value for value in values if value)
    return normalize_korean_text(text) or None


@dataclass(frozen=True)
class RegionWithinRadiusCenter:
    """kor-travel-geo v2 반경 행정구역 질의 중심점. 외부 순서는 ``(lon, lat)``."""

    lon: float
    lat: float


@dataclass(frozen=True)
class RegionWithinRadiusItem:
    """kor-travel-geo v2 반경 안에 포함/교차하는 행정구역."""

    code: str
    name: str | None
    relation: RegionWithinRadiusRelation


@dataclass(frozen=True)
class RegionsWithinRadiusResponse:
    """kor-travel-geo v2 ``POST /v2/regions/within-radius`` 응답."""

    center: RegionWithinRadiusCenter
    radius_km: float
    sido: tuple[RegionWithinRadiusItem, ...] = ()
    sigungu: tuple[RegionWithinRadiusItem, ...] = ()
    emd: tuple[RegionWithinRadiusItem, ...] = ()


# -- 순수 변환 함수 -----------------------------------------------------------


def _usable_reverse_candidates(
    response: KraddrReverseV2Response,
    *,
    max_distance_m: float | None,
) -> tuple[KraddrCandidateV2, ...]:
    if response.status != _STATUS_OK:
        return ()
    if max_distance_m is None:
        return response.candidates
    return tuple(
        candidate
        for candidate in response.candidates
        if candidate.distance_m is None or candidate.distance_m <= max_distance_m
    )


def _reverse_sigungu_names(
    response: KraddrReverseV2Response,
    *,
    max_distance_m: float | None,
) -> tuple[str, ...]:
    names: list[str] = []
    for candidate in _usable_reverse_candidates(
        response, max_distance_m=max_distance_m
    ):
        name = normalize_korean_text(
            candidate.region.sigungu if candidate.region is not None else None
        )
        if name and name not in names:
            names.append(name)
    return tuple(names)


def reverse_response_to_address(
    response: KraddrReverseV2Response,
    *,
    max_distance_m: float | None = None,
) -> Address | None:
    """kor-travel-geo ``POST /v2/reverse`` 응답 → 본 라이브러리 ``Address``.

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
    피한다 (kor-travel-geo가 비정형 코드를 돌려줘도 reverse 전체가 깨지지 않게).
    """
    cands = _usable_reverse_candidates(
        response, max_distance_m=max_distance_m
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
    response: KorTravelGeocodeV2Response,
    *,
    min_confidence: float = 0.0,
) -> Coordinate | None:
    """kor-travel-geo ``POST /v2/geocode`` 응답 → ``Coordinate`` (WGS84).

    ``status != "OK"`` 이거나 좌표 있는 candidate가 없으면 ``None``.
    ``confidence``가 ``min_confidence`` 미만인 candidate는 제외하고, 남은 것 중
    confidence 최댓값 candidate의 ``point.lon/lat``을 좌표로 옮긴다. 이전
    pre-ADR-062 응답(``point.x/y``)은 REST 파서에서만 호환 fallback으로 받는다.
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
        return Coordinate(lon=Decimal(str(point.lon)), lat=Decimal(str(point.lat)))
    except (InvalidOperation, ValueError):
        return None


def geocode_response_to_address(
    response: KorTravelGeocodeV2Response,
    *,
    min_confidence: float = 0.0,
) -> Address | None:
    """kor-travel-geo ``POST /v2/geocode`` 응답 → 행정코드 보강 ``Address``.

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


# -- kor-travel-geo REST 응답 파싱용 frozen dataclass (Protocol 만족) ---------------


@dataclass(frozen=True)
class _RestPoint:
    lon: float
    lat: float


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
    #: 응답 최상위 ``dataset``(geo ADR-069 D7). 없는 옛 응답·형식 위반이면 None(ADR-109 결정 2).
    dataset: DatasetRef | None = None


@dataclass(frozen=True)
class _RestGeocodeV2Response:
    status: str
    candidates: tuple[_RestCandidateV2, ...] = field(default_factory=tuple)
    dataset: DatasetRef | None = None


def _parse_point(data: dict[str, Any] | None) -> _RestPoint | None:
    if not data:
        return None
    lon_raw = data.get("lon", data.get("x"))
    lat_raw = data.get("lat", data.get("y"))
    if lon_raw is None or lat_raw is None:
        return None
    try:
        return _RestPoint(lon=float(lon_raw), lat=float(lat_raw))
    except (TypeError, ValueError):
        return None


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


def _parse_optional_dataset(data: dict[str, Any]) -> DatasetRef | None:
    """응답 최상위 ``dataset``의 **선택** 파싱 — 없거나 형식이 틀리면 None.

    이 값은 run-scoped 현재 토큰과의 불일치 관측에만 쓰인다(ADR-109 결정 2). 형식이 틀린 값 때문에
    지오코딩 응답 자체를 버리면 geo의 사소한 계약 어긋남이 적재 실패로 번진다 — 그래서 여기서는
    삼킨다. 현재 토큰(:meth:`KorTravelGeoRestClient.dataset_version`)은 반대로 엄격하다.
    """
    raw = data.get("dataset")
    if not isinstance(raw, dict):
        return None
    try:
        return DatasetRef.model_validate(raw)
    except ValueError:
        return None


def _parse_reverse_response(data: dict[str, Any]) -> _RestReverseV2Response:
    cands = tuple(_parse_candidate_v2(c) for c in data.get("candidates", ()))
    return _RestReverseV2Response(
        status=str(data.get("status", "ERROR")),
        candidates=cands,
        dataset=_parse_optional_dataset(data),
    )


def _parse_geocode_response(data: dict[str, Any]) -> _RestGeocodeV2Response:
    cands = tuple(_parse_candidate_v2(c) for c in data.get("candidates", ()))
    return _RestGeocodeV2Response(
        status=str(data.get("status", "ERROR")),
        candidates=cands,
        dataset=_parse_optional_dataset(data),
    )


def _parse_dataset_version_response(data: dict[str, Any]) -> DatasetRef | None:
    """``POST /v2/dataset/version`` → 현재 ``DatasetRef``.

    활성 릴리스가 없으면(``available=false``) None.

    엄격하다 — ``available``이 bool이 아니거나, 참인데 ``current.version_token``이 없거나 토큰
    형식이 틀리면 ``ValueError``(호출부에서 typed provider 오류로 바뀐다). run의 현재
    토큰은 스탬프의 비교 키라 틀린 값을 받아들이면 모든 행이 영구 stale이 된다.
    """
    available = data.get("available")
    if not isinstance(available, bool):
        raise ValueError("kor-travel-geo dataset/version response available must be a bool")
    if not available:
        return None
    current = data.get("current")
    if not isinstance(current, dict):
        raise ValueError("kor-travel-geo dataset/version response current must be an object")
    return DatasetRef.model_validate(
        {
            "version_token": current.get("version_token"),
            "data_token": current.get("data_token"),
            **_dataset_observation_fields(current),
        }
    )


def _dataset_observation_fields(current: dict[str, Any]) -> dict[str, Any]:
    """``current``의 관측용 필드(``activated_at``·``reference_months``) — **선택** 파싱.

    토큰과 달리 비교 키가 아니므로 형식이 틀리면 버린다(현재 토큰 판정을 막지 않는다).
    """
    fields: dict[str, Any] = {}
    activated_at = current.get("activated_at")
    if isinstance(activated_at, str):
        with contextlib.suppress(ValueError):
            fields["activated_at"] = datetime.fromisoformat(activated_at)
    months = current.get("reference_months")
    if isinstance(months, dict) and all(
        isinstance(key, str) and isinstance(value, str) for key, value in months.items()
    ):
        fields["reference_months"] = dict(months)
    return fields


def _parse_region_center(data: dict[str, Any]) -> RegionWithinRadiusCenter:
    raw = data.get("center")
    if not isinstance(raw, dict):
        raise ValueError("kor-travel-geo regions response center must be an object")
    lon_raw = raw.get("lon", raw.get("x"))
    lat_raw = raw.get("lat", raw.get("y"))
    if lon_raw is None or lat_raw is None:
        raise ValueError("kor-travel-geo regions response center has invalid lon/lat")
    try:
        return RegionWithinRadiusCenter(lon=float(lon_raw), lat=float(lat_raw))
    except (TypeError, ValueError) as exc:
        raise ValueError("kor-travel-geo regions response center has invalid lon/lat") from exc


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
        raise ValueError("kor-travel-geo regions response radius_km is invalid") from exc
    if radius_km <= 0:
        raise ValueError("kor-travel-geo regions response radius_km must be positive")
    return RegionsWithinRadiusResponse(
        center=center,
        radius_km=radius_km,
        sido=_parse_region_items(data, "sido"),
        sigungu=_parse_region_items(data, "sigungu"),
        emd=_parse_region_items(data, "emd"),
    )


def _regions_within_radius_response_to_address(
    response: RegionsWithinRadiusResponse,
) -> Address | None:
    """중심 좌표가 포함된 행정구역 응답 → 최소 ``Address`` 보강값."""
    emd = _contains_region_item(response.emd)
    sigungu = _contains_region_item(response.sigungu)
    sido = _contains_region_item(response.sido)

    bjd_code = _bjd_code_from_emd_code(emd.code if emd is not None else None)
    sigungu_code = extract_sigungu_code(bjd_code) or _five_digits_or_none(
        sigungu.code if sigungu is not None else None
    )
    sido_code = extract_sido_code(bjd_code) or _two_digits_or_none(
        sido.code if sido is not None else None
    )
    if sido_code is None and sigungu_code is not None:
        sido_code = _two_digits_or_none(sigungu_code[:2])
    if bjd_code is None and sigungu_code is None and sido_code is None:
        return None

    return Address(
        legal=_region_names(
            sido.name if sido is not None else None,
            sigungu.name if sigungu is not None else None,
            emd.name if emd is not None else None,
        ),
        admin=normalize_korean_text(emd.name if emd is not None else None),
        bjd_code=bjd_code,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        sido_name=normalize_korean_text(sido.name if sido is not None else None),
        sigungu_name=normalize_korean_text(
            sigungu.name if sigungu is not None else None
        ),
    )


# -- kor-travel-geo REST 클라이언트 -----------------------------------------------


REVERSE_RESULT_EMPTY_KEY: Final[str] = "reverse_result"
"""``GeoCallStats.empty``의 **행 단위 최종** 빈 답 키(reverse·region fallback 둘 다 빈 결과).

endpoint 키(``reverse``·``regions_within_radius``)와 달리 이것은 역지오코더가 돌려준 결과가
비었는가다. run 빈 답 가드(ADR-109 결정 4)의 분자다 — 분모는 ``calls['reverse']``(좌표 있는 행 수).
산악 centroid처럼 reverse가 거의 늘 비고 fallback이 채우는 dataset에서 endpoint 키를 쓰면 정상 run이
실패한다.
"""


@dataclass
class GeoCallStats:
    """geo 경계를 **몇 번 넘었는지**를 endpoint별로 센다.

    **왜 endpoint별인가.** dagster의 reverse geocoder는
    ``region_fallback_radius_km=0.1``로 결선돼 있어서, 첫 ``/v2/reverse``가 법정동코드를
    못 채우면 같은 좌표로 ``/v2/regions/within-radius``를 **한 번 더** 친다
    (:meth:`_KorTravelGeoObservedReverseGeocoder.observe`). 즉 행 하나가 왕복 1회일
    수도 2회일 수도 있는데, **그 수가 오늘 어디에도 없다** — 이 저장소에도, geo
    저장소의 벤치마크에도 없다. 합계만 세면 "느린 것이 reverse인가 fallback인가"를
    영원히 못 가른다.

    그 질문이 실무를 가른다. 2026-09-19에 산악 등산로 적재가 3시간 넘게 이벤트 없이
    돌았는데, 산악 centroid는 도로명주소 후보가 없어 fallback이 거의 전량에 걸릴
    것으로 **추정**될 뿐 측정된 적이 없다. 추정 위에 동시성이나 재시도 수치를 얹으면
    분모가 틀린 채로 정확한 분자를 계산하게 된다.

    **이 클래스는 아무것도 바꾸지 않는다.** 세기만 한다. 재시도도, 차단도, 지연도
    없다 — 그 결정들의 분모를 먼저 만드는 것이 목적이다.

    수명은 주입한 쪽이 갖는다(resource 하나 = 카운터 하나). 모듈 전역에 두지 않는
    이유는 ADR-030(라이브러리 in-memory 캐시 금지)과 같은 것이다 — 프로세스 수명
    상태를 라이브러리가 소유하면 누가 언제 리셋하는지가 사라진다.
    """

    calls: Counter[str] = field(default_factory=Counter)
    """endpoint별 **시도** 수. 성공·실패를 모두 센다."""

    failures: Counter[str] = field(default_factory=Counter)
    """endpoint별 **전송 실패** 수(``calls``의 부분집합)."""

    empty: Counter[str] = field(default_factory=Counter)
    """endpoint별 **빈 답** 수 — 예외 없이 끝났는데 ``Address``가 None이거나 ``bjd_code``가 None.

    ``failures``와 겹치지 않는다(빈 답은 전송 실패가 아니다). ADR-109 결정 4 run 가드의 분자다.
    역지오코더(:meth:`_KorTravelGeoObservedReverseGeocoder.observe`)가 endpoint 단위로 기록한다 —
    reverse가 비고 region fallback이 채우면 ``reverse``는 빈 답 1건이고 fallback은 별도 endpoint다.
    """

    observed_data_tokens: set[str] = field(default_factory=set)
    """응답 ``dataset.data_token``으로 관측한 토큰 집합(ADR-109 결정 2).

    run-scoped 현재 토큰과 다른 값이 있으면 그 run 도중 릴리스가 바뀐 것이다(경고 + 메타만).
    """

    def record(self, endpoint: str, *, failed: bool) -> None:
        self.calls[endpoint] += 1
        if failed:
            self.failures[endpoint] += 1

    def record_empty(self, endpoint: str) -> None:
        self.empty[endpoint] += 1

    def observe_dataset(self, dataset: DatasetRef | None) -> None:
        if dataset is not None and dataset.data_token is not None:
            self.observed_data_tokens.add(dataset.data_token)

    @property
    def total_calls(self) -> int:
        return sum(self.calls.values())

    def as_metadata(self) -> dict[str, int]:
        """Dagster metadata/로그에 실을 평평한 계수."""

        metadata = {f"geo_calls_{name}": count for name, count in self.calls.items()}
        metadata.update(
            {f"geo_failures_{name}": count for name, count in self.failures.items()}
        )
        metadata.update({f"geo_empty_{name}": count for name, count in self.empty.items()})
        metadata["geo_calls_total"] = self.total_calls
        metadata["geo_failures_total"] = sum(self.failures.values())
        metadata["geo_empty_total"] = sum(self.empty.values())
        return metadata

    def summary(self) -> str:
        """한 줄 요약. **0건도 말한다** — 침묵과 0을 구별할 수 있어야 한다."""

        if not self.calls:
            return "geo 경계 호출 0건"
        parts = [
            f"{name}={self.calls[name]}"
            + (f"(실패 {self.failures[name]})" if self.failures[name] else "")
            for name in sorted(self.calls)
        ]
        return f"geo 경계 호출 {self.total_calls}건 — " + " ".join(parts)


class KorTravelGeoRestClient:
    """kor-travel-geo REST API v2 (``POST /v2/{reverse,geocode}``) 비동기 클라이언트.

    ``httpx.AsyncClient``를 주입받아 ``POST /v2/reverse`` / ``POST /v2/geocode``를
    호출하고 JSON을 structural 응답 객체로 파싱한다. 호스트는 주입한
    ``httpx.AsyncClient``의 ``base_url``로 설정 (로컬 개발 예:
    ``httpx.AsyncClient(base_url="http://127.0.0.1:12501")``), 경로 prefix는
    ``base_path`` (기본 ``/v2``). client 수명은 호출자 책임 (ADR-002).
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        base_path: str = "/v2",
        api_key: SecretStr | None = None,
        require_auth: bool = True,
        stats: GeoCallStats | None = None,
    ) -> None:
        """backend-to-backend public API key 인증을 생성 시점에 검증한다.

        key는 URL query가 아니라 ``X-KTG-API-Key`` header로만 전송한다. Map은 public
        endpoint만 호출하므로 geo admin trusted-proxy 권한을 요구하거나 위임하지 않는다.

        mock transport로만 도는 테스트처럼 인증이 필요 없는 경우에만 명시적으로
        ``require_auth=False``로 opt-out한다.
        """
        self._http = http_client
        self._base = base_path.rstrip("/")
        self._api_key = api_key
        # 기본값 None = **현행 동작과 같다.** 계측을 켜는 것은 주입한 쪽의 결정이고,
        # 그래야 호출자 여덟 곳 중 어느 것도 우연히 달라지지 않는다.
        self._stats = stats
        if require_auth:
            self.preflight()

    def _endpoint(self, path: str) -> str:
        """계수 키. ``/v2/regions/within-radius`` → ``regions_within_radius``."""

        suffix = path[len(self._base) :] if path.startswith(self._base) else path
        return suffix.strip("/").replace("/", "_").replace("-", "_") or "root"

    def preflight(self) -> None:
        """geo public API key **결선**을 확인한다 (형태만).

        ⚠️ 이 검사는 값이 *무엇인지* 보지 않는다. 다른 서비스의 키를 여기 넣어도 통과한다 —
        2026-08-13 prod 사고가 정확히 그것이었다(VWorld 키가 결선돼 geo가 401로 거부).
        의미 검증은 :meth:`verify_credentials`가 하고, 그건 네트워크가 필요해 별도다.
        """
        if self._api_key is None:
            raise GeoAuthNotConfiguredError(
                "kor-travel-geo public API key가 설정되지 않았습니다. "
                "KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY를 설정하세요."
            )
        key = self._api_key.get_secret_value().strip()
        if not key:
            raise GeoAuthNotConfiguredError(
                "kor-travel-geo public API key가 비어 있습니다. "
                "KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY를 설정하세요."
            )
        if len(key) > 128:
            raise GeoAuthNotConfiguredError(
                "kor-travel-geo public API key는 128자 이하여야 합니다."
            )

    async def verify_credentials(self) -> None:
        """geo가 이 키를 **실제로 받아들이는지** 1회 호출로 확인한다.

        :meth:`preflight`는 형태만 본다. 다른 서비스의 키를 넣어도 통과하므로,
        "설정돼 있다"와 "동작한다" 사이의 간극을 여기서 메운다.

        판정은 두 갈래이고 **의도적으로 비대칭**이다.

        - **키가 거부되면 던진다**(fail-close). geo가 400 ``E0100 field=key`` 또는 401
          ``E0401``로 답하면 그 키로는 어떤 지오코딩도 성공하지 못한다. 그 상태로 기동하면
          정/역지오코딩이 전부 실패하는 서비스가 healthy로 뜬다.
        - **도달 못 하면 던지지 않는다**(fail-open). geo는 별도 stack이라, 그쪽 지연이
          map 전체의 부팅 교착이 되면 안 된다. 이 경우는 호출자가 경고를 남긴다.

        네트워크는 **주입된 클라이언트**로 나간다. 이 모듈은 httpx를 런타임 의존으로 갖지
        않으며(ADR-006/044) client 수명은 호출자 책임이다(ADR-002).

        Raises:
            GeoAuthNotConfiguredError: 키가 미설정·형태 위반이거나 geo가 거부했을 때.
            GeoRequestError: 도달 실패·5xx 등 **판정 불가**. 호출자가 삼킬지 정한다.
        """
        self.preflight()
        # 가장 싼 유효 요청. 좌표는 어디든 되지만 결과를 쓰지 않으므로 최소 옵션만 켠다.
        resp = await self._post(
            f"{self._base}/reverse",
            json={
                "lon": 127.0,
                "lat": 37.5,
                "include_region": False,
                "include_zipcode": False,
            },
        )
        if _is_public_key_rejection(resp):
            raise GeoAuthNotConfiguredError(
                "kor-travel-geo가 Map public API key를 거부했습니다. "
                "다른 서비스의 키(예: VWorld)가 결선돼 있지 않은지 확인하세요 — "
                "형태 검사는 그것을 잡지 못합니다."
            )
        if resp.status_code >= 500:
            raise GeoRequestError(
                f"kor-travel-geo 상태 확인 불가: {resp.status_code} "
                f"{resp.reason_phrase}"
            )
        # 2xx/4xx(키 거부 아님)는 키가 받아들여졌다는 뜻이다. 본문은 보지 않는다 —
        # 이 메서드가 답하는 질문은 "이 키가 먹히는가"뿐이다.

    def _public_api_headers(self) -> dict[str, str] | None:
        if self._api_key is None:
            return None
        return {"X-KTG-API-Key": self._api_key.get_secret_value().strip()}

    async def _post(self, path: str, *, json: dict[str, Any]) -> httpx.Response:
        """transport 오류도 원본 request를 연결하지 않는 typed 예외로 바꾼다."""
        import httpx as _httpx

        response: httpx.Response | None = None
        sanitized: GeoRequestError | None = None
        try:
            response = await self._http.post(
                path,
                json=json,
                headers=self._public_api_headers(),
            )
        except _httpx.HTTPError as exc:
            sanitized = GeoRequestError(
                f"kor-travel-geo transport 실패: {type(exc).__name__}"
            )
        # **던지기 전에 센다.** 실패한 왕복도 왕복이고, 실패한 run이야말로 그 수가
        # 가장 필요한 run이다. except 블록 **밖**이므로 키가 든 원본 예외의
        # ``__context__``가 생기지 않는다(위 주석의 계약을 그대로 지킨다).
        if self._stats is not None:
            self._stats.record(self._endpoint(path), failed=sanitized is not None)
        if sanitized is not None:
            raise sanitized
        assert response is not None
        return response

    async def reverse(
        self,
        x: float,
        y: float,
        *,
        include_region: bool = True,
        include_zipcode: bool = True,
        radius_m: int | None = None,
    ) -> _RestReverseV2Response:
        """``POST /v2/reverse`` — 좌표(x=lon, y=lat) 역지오코딩.

        메서드 인자는 기존 caller 호환을 위해 ``x``/``y`` 이름을 유지하지만, wire
        body는 kor-travel-geo v2 정본인 ``lon``/``lat``로 전송한다.
        """
        body: dict[str, Any] = {
            "lon": x,
            "lat": y,
            "include_region": include_region,
            "include_zipcode": include_zipcode,
        }
        if radius_m is not None:
            body["radius_m"] = radius_m
        resp = await self._post(f"{self._base}/reverse", json=body)
        _raise_for_status_sanitized(resp)
        parsed = _parse_response_sanitized(resp, _parse_reverse_response)
        if self._stats is not None:
            self._stats.observe_dataset(parsed.dataset)
        return parsed

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
        resp = await self._post(f"{self._base}/geocode", json=body)
        _raise_for_status_sanitized(resp)
        parsed = _parse_response_sanitized(resp, _parse_geocode_response)
        if self._stats is not None:
            self._stats.observe_dataset(parsed.dataset)
        return parsed

    async def dataset_version(self) -> DatasetRef | None:
        """``POST /v2/dataset/version`` (본문 ``{}``) — geo가 지금 서빙하는 데이터셋.

        활성 릴리스가 없으면 None. ``data_token``이 없는 릴리스(지문 backfill 전)는
        ``DatasetRef(data_token=None)``이다 — 소비자는 그것을 "판정 불가"로 읽는다(ADR-109 결정 2).
        전송 실패·HTTP 오류·계약 위반은 다른 메서드와 같은 typed 예외로 올린다. 실패를 None으로
        바꿔 run을 계속할지는 호출자(run-scoped resource, T-GR-02)가 정한다.
        """
        resp = await self._post(f"{self._base}/dataset/version", json={})
        _raise_for_status_sanitized(resp)
        return _parse_response_sanitized(resp, _parse_dataset_version_response)

    def _note_empty(self, endpoint: str) -> None:
        if self._stats is not None:
            self._stats.record_empty(endpoint)

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
        resp = await self._post(f"{self._base}/regions/within-radius", json=body)
        _raise_for_status_sanitized(resp)
        return _parse_response_sanitized(
            resp,
            _parse_regions_within_radius_response,
        )


# -- kor-travel-geo REST client → 콜러블 팩토리 -----------------------------------


class _KorTravelGeoObservedReverseGeocoder:
    def __init__(
        self,
        client: KorTravelGeoRestClient,
        *,
        radius_m: int | None,
        max_distance_m: float | None,
        region_fallback_radius_km: float | None,
    ) -> None:
        self._client = client
        self._radius_m = radius_m
        self._max_distance_m = max_distance_m
        self._region_fallback_radius_km = region_fallback_radius_km

    @property
    def stats(self) -> GeoCallStats | None:
        """주입된 client의 경계 계수(없으면 None). 적재 wrapper가 관측 토큰 불일치를 본다."""
        return self._client._stats

    async def observe(self, coord: Coordinate) -> ReverseGeocodeObservation:
        observation = await self._observe(coord)
        address = observation.address
        if address is None or address.bjd_code is None:
            # 행 단위 최종 빈 답 — region fallback까지 거친 결과다(run 빈 답 가드의 분자).
            self._client._note_empty(REVERSE_RESULT_EMPTY_KEY)
        return observation

    async def _observe(self, coord: Coordinate) -> ReverseGeocodeObservation:
        response = await self._client.reverse(
            float(coord.lon), float(coord.lat), radius_m=self._radius_m
        )
        address = reverse_response_to_address(
            response, max_distance_m=self._max_distance_m
        )
        names = list(
            _reverse_sigungu_names(
                response, max_distance_m=self._max_distance_m
            )
        )
        if address is None or address.bjd_code is None:
            self._client._note_empty("reverse")
        if (
            address is not None and address.bjd_code is not None
        ) or self._region_fallback_radius_km is None:
            return ReverseGeocodeObservation(address, tuple(names))

        regions = await self._client.regions_within_radius(
            lon=float(coord.lon),
            lat=float(coord.lat),
            radius_km=self._region_fallback_radius_km,
            levels=("sido", "sigungu", "emd"),
        )
        for item in regions.sigungu:
            name = normalize_korean_text(item.name)
            if name and name not in names:
                names.append(name)
        region_address = _regions_within_radius_response_to_address(regions)
        if region_address is None or region_address.bjd_code is None:
            self._client._note_empty("regions_within_radius")
        if address is None or region_address is None:
            return ReverseGeocodeObservation(
                region_address or address,
                tuple(names),
            )
        merged = address.model_copy(
            update={
                "legal": address.legal or region_address.legal,
                "admin": address.admin or region_address.admin,
                "bjd_code": region_address.bjd_code,
                "sigungu_code": region_address.sigungu_code
                or address.sigungu_code,
                "sido_code": region_address.sido_code or address.sido_code,
                "sido_name": address.sido_name or region_address.sido_name,
                "sigungu_name": address.sigungu_name
                or region_address.sigungu_name,
            }
        )
        return ReverseGeocodeObservation(merged, tuple(names))

    async def __call__(self, coord: Coordinate) -> Address | None:
        return (await self.observe(coord)).address


_LOGGER = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def open_geo_client(
    settings: KorTravelMapSettings,
    *,
    logger: logging.Logger | None = None,
) -> AsyncIterator[KorTravelGeoRestClient | None]:
    """settings로 짧은 수명 geo client를 열고 닫는다 — 열 수 없으면 None을 준다.

    base URL이 없거나 API key가 형태 위반이면 None(+ key 위반은 WARNING 1건)이다. 호출자는 None을
    :func:`fetch_current_dataset` 등에 그대로 넘긴다(그쪽이 "client 없음"을 같은 규칙으로 처리한다).
    운영 API(``/v1/ops/geo-releases``)와 릴리스 센서(T-GR-05)가 이 하나를 쓴다 — client 생성
    지점을 줄인다(acceptance §T-GR-05의 ``kor_travel_geo_client_resource`` 대신 이 helper — 소유자
    위임 결정).
    """
    import httpx as _httpx  # noqa: PLC0415 — 모듈 머리의 httpx는 TYPE_CHECKING 전용이다

    log = logger if logger is not None else _LOGGER
    if settings.kor_travel_geo_base_url is None:
        yield None
        return
    async with _httpx.AsyncClient(
        base_url=settings.kor_travel_geo_base_url.get_secret_value(),
        timeout=geo_http_timeout(settings),
    ) as http:
        try:
            client = KorTravelGeoRestClient(http, api_key=settings.kor_travel_geo_api_key)
        except GeoAuthNotConfiguredError:
            log.warning(
                "kor-travel-geo API key 미설정·형태 위반(KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY) — "
                "geo client 없이 진행한다"
            )
            yield None
            return
        yield client


async def fetch_current_dataset(
    client: KorTravelGeoRestClient | None,
    *,
    logger: logging.Logger | None = None,
) -> DatasetRef | None:
    """run 시작에 geo의 현재 데이터셋을 **한 번** 읽는다 — run-scoped 현재 토큰(ADR-109 결정 2).

    asset·큐 runner(Dagster resource ``kor_travel_geo_dataset``)·offline upload·CLI가 모두 이
    함수를 쓴다(팩토리 1개). 실패는 run을 멈추지 않는다 — client가 없거나(base URL 미설정),
    geo가 답하지 못하거나(전송·HTTP·계약 오류, 키 거부), 활성 릴리스가 없으면(``available=false``)
    **None + WARNING 1건**이다. None이면 적재 경로의 stale 분기가 꺼져 토큰 도입 전과 같아진다
    (fail-to-current — geo 장애가 전량 재변환으로 번지지 않는다).

    ``data_token``이 None인 ``DatasetRef``(지문 backfill 전)는 그대로 돌려준다 — 판정 불가는
    소비자(적재 경로·센서)가 같은 규칙으로 처리한다. 경고는 내지 않는다(geo가 답했다).

    ``logger``는 경고를 낼 logger다 — Dagster 경로는 ``managed_python_loggers``에 든 logger(또는
    ``context.log``)를 넘겨야 경고가 event stream에 닿는다(2026-09-19 "이벤트 0건"과 같은 부류).
    """
    log = logger if logger is not None else _LOGGER
    if client is None:
        log.warning(
            "kor-travel-geo 현재 데이터셋: client 없음(base URL 미설정) — 이 run의 현재 토큰은 None"
        )
        return None
    try:
        current = await client.dataset_version()
    except (GeoRequestError, GeoAuthNotConfiguredError) as exc:
        log.warning(
            "kor-travel-geo 현재 데이터셋 조회 실패(%s) — 이 run의 현재 토큰은 None",
            type(exc).__name__,
        )
        return None
    if current is None:
        log.warning(
            "kor-travel-geo 현재 데이터셋: 활성 릴리스 없음(available=false) — "
            "이 run의 현재 토큰은 None"
        )
    return current


def geo_dataset_mismatch(
    current: DatasetRef | None, observed_data_tokens: Iterable[str]
) -> bool:
    """run 도중 응답이 run-scoped 현재 토큰과 **다른** ``data_token``을 냈는가(ADR-109 결정 2).

    현재 토큰이 없으면(None 또는 ``data_token`` None) 비교할 기준이 없어 False다. 참이면 그 run의
    스탬프는 옛 토큰으로 찍히고 다음 센서 tick이 새 토큰으로 다시 계획한다(안전 방향) — 호출자는
    WARNING 1건과 메타 ``geo_dataset_mismatch=true``만 남긴다.
    """
    if current is None or current.data_token is None:
        return False
    return any(token != current.data_token for token in observed_data_tokens)


def kor_travel_geo_reverse_geocoder(
    client: KorTravelGeoRestClient,
    *,
    radius_m: int | None = None,
    max_distance_m: float | None = None,
    region_fallback_radius_km: float | None = None,
) -> ObservedReverseGeocoder:
    """kor-travel-geo REST client → 대표 주소와 후보집합을 보존하는 역지오코더.

    일반 ``ReverseGeocoder``처럼 호출하면 대표 ``Address``만 반환하고, ``observe``는
    경계 좌표 검증에 필요한 reverse 후보 전체의 시군구명도 함께 반환한다.
    ``region_fallback_radius_km``를 지정하면 주소 후보가 없을 때 중심 좌표가 포함된
    행정구역을 조회해 최소 코드를 보강한다.
    """
    return _KorTravelGeoObservedReverseGeocoder(
        client,
        radius_m=radius_m,
        max_distance_m=max_distance_m,
        region_fallback_radius_km=region_fallback_radius_km,
    )


def kor_travel_geo_address_geocoder(
    client: KorTravelGeoRestClient,
    *,
    min_confidence: float = 0.0,
    fallback: Literal["none", "api"] = "none",
) -> AddressGeocoder:
    """kor-travel-geo REST client → ``AddressGeocoder`` (``Address`` → 좌표) 콜러블.

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


def kor_travel_geo_address_resolver(
    client: KorTravelGeoRestClient,
    *,
    min_confidence: float = 0.0,
    fallback: Literal["none", "api"] = "none",
) -> AddressResolver:
    """kor-travel-geo REST client → ``AddressResolver`` (주소 → 행정코드 보강) 콜러블.

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
    client: KorTravelGeoRestClient,
    *,
    lon: float,
    lat: float,
    radius_km: float,
    levels: tuple[RegionWithinRadiusLevel, ...] = ("sigungu", "emd"),
) -> RegionsWithinRadiusResponse:
    """kor-travel-geo REST v2로 POI 반경 행정구역을 조회한다."""
    return await client.regions_within_radius(
        lon=lon,
        lat=lat,
        radius_km=radius_km,
        levels=levels,
    )


async def resolve_sigungu_by_radius(
    client: KorTravelGeoRestClient,
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
