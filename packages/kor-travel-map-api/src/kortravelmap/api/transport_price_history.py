"""``kortravelmap.api.transport_price_history`` — transport 출처 가격 추이를 transport에서 읽는다 (ADR-114 결정 6).

Map은 kor-travel-transport 출처 데이터의 이력을 보관하지 않는다(``core.retention``). 그래서 price card의
**history**는 그 dataset에 한해 Map DB가 아니라 transport의 가격 이력 export에서 온다. **current**는 언제나
Map DB summary다 — transport가 죽어도 현재가는 나온다.

- 어느 dataset의 추이를 transport가 줄 수 있는가: :data:`TRANSPORT_HISTORY_DATASETS`. 휴게소 유가는 transport에
  이력이 없어(휴게소당 최신 1행) 여기 없다 → ``history_source = "unavailable"``.
- 실패(미설정·timeout·404/5xx·계약 위반)는 예외가 아니라 ``None``이다. 라우터는 history를 Map DB 값(현재
  winner)으로 두고 ``history_source = "unavailable"``을 낸다 — 200이다.
- 공개 라우트가 부르므로 증폭을 막는다: 짧은 timeout(연결 1초·읽기 3초 상한), 현재 card 응답의 TTL cache
  (주유소마다 5분), 실패 뒤 60초 동안 호출하지 않는 차단기.
- series 대응: Map price feature의 자연키(identity claim) = 오피넷 ``uni_id`` = transport
  ``fuel_stations.source_station_id``. 유종: transport ``product_code`` → ``OPINET_PRODUCT_KEY_MAP``.
  이력 점의 ``observed_at`` = transport ``observed_at``(오피넷 갱신시각), ``known_at`` = transport
  ``collected_at``(그 가격을 마지막으로 확인한 수집 시각 — knowledge time이 아니다). 가격이 비어 있는 행
  (판매 안 함)은 점이 아니므로 버린다.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from time import monotonic
from typing import TYPE_CHECKING, Final, Literal
from urllib.parse import quote

import httpx

from kortravelmap.dto.price import PriceDomain
from kortravelmap.infra.price_repo import FeaturePriceDataset, PricePoint, sort_current_points
from kortravelmap.providers.kor_travel_transport import (
    DATASET_KEY_FUEL_PRICES,
    EXPORT_PATH_FUEL_STATION_PRICE_HISTORY,
    KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
    SERVICE_TOKEN_HEADER,
    TransportExportContractError,
    TransportFuelPriceHistory,
    parse_fuel_price_history,
)
from kortravelmap.providers.opinet import OPINET_PRODUCT_KEY_MAP, OPINET_PRODUCT_NAME_KO

if TYPE_CHECKING:
    from kortravelmap.settings import KorTravelMapSettings

__all__ = [
    "HistorySource",
    "TRANSPORT_HISTORY_DATASETS",
    "TransportPriceHistoryReader",
    "merge_transport_history",
    "transport_http_timeout",
]

_LOG = logging.getLogger(__name__)

HistorySource = Literal["map", "kor_travel_transport", "unavailable"]
"""price card ``history``의 출처. 응답 필드 ``history_source``의 값 집합."""

TRANSPORT_HISTORY_DATASETS: Final[frozenset[tuple[str, str]]] = frozenset(
    {(KOR_TRAVEL_TRANSPORT_PROVIDER_NAME, DATASET_KEY_FUEL_PRICES)}
)
"""transport가 가격 이력을 주는 latest-only dataset. 휴게소 유가는 없다(transport에 이력이 없다)."""

_READ_BUDGET_SECONDS: Final[float] = 3.0
_CONNECT_BUDGET_SECONDS: Final[float] = 1.0
_CACHE_TTL_SECONDS: Final[float] = 300.0
_BREAKER_SECONDS: Final[float] = 60.0
_CACHE_MAX_ENTRIES: Final[int] = 4096


def transport_http_timeout(settings: KorTravelMapSettings) -> httpx.Timeout:
    """API 경로의 transport timeout — 설정값과 공개 라우트 예산 중 짧은 쪽(ADR-110 결정 3, ADR-114).

    Dagster fetcher의 같은 이름 함수와 같은 규약(연결 수립 분리)이고, 공개 라우트에서 한 요청이 transport를
    기다리는 시간만 더 짧게 자른다. ``tests/lint/test_geo_transport_clients_use_timeout_factory.py``가
    생성 지점마다 이 호출을 강제한다.
    """
    return httpx.Timeout(
        min(settings.kor_travel_transport_timeout_seconds, _READ_BUDGET_SECONDS),
        connect=min(settings.kor_travel_transport_connect_timeout_seconds, _CONNECT_BUDGET_SECONDS),
    )


def _transport_connection(settings: KorTravelMapSettings) -> tuple[str, dict[str, str]] | None:
    """base URL과 인증 header. 미설정(빈 문자열 포함, compose ``${X:-}``)이면 ``None``."""
    base_url = (settings.kor_travel_transport_base_url or "").strip()
    token = settings.kor_travel_transport_service_token
    secret = token.get_secret_value().strip() if token is not None else ""
    if not base_url or not secret:
        return None
    return base_url.rstrip("/"), {SERVICE_TOKEN_HEADER: secret}


@dataclass
class TransportPriceHistoryReader:
    """프로세스 하나가 공유하는 transport 가격 이력 reader(cache·차단기 포함)."""

    settings: KorTravelMapSettings
    _cache: dict[tuple[str, int], tuple[float, TransportFuelPriceHistory]] = field(
        default_factory=dict
    )
    _open_until: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def fuel_price_history(
        self,
        *,
        natural_key: str,
        limit: int,
        until: datetime | None = None,
    ) -> TransportFuelPriceHistory | None:
        """주유소 한 곳의 가격 이력. 쓸 수 없으면 ``None``(라우터가 ``unavailable``로 낸다)."""
        cache_key = (natural_key, limit)
        now = monotonic()
        if until is None:
            cached = self._cache.get(cache_key)
            if cached is not None and cached[0] > now:
                return cached[1]
        if self._open_until > now:
            return None
        history = await self._fetch(natural_key=natural_key, limit=limit, until=until)
        if history is None:
            self._open_until = monotonic() + _BREAKER_SECONDS
            return None
        if until is None:
            async with self._lock:
                if len(self._cache) >= _CACHE_MAX_ENTRIES:
                    self._cache.clear()
                self._cache[cache_key] = (monotonic() + _CACHE_TTL_SECONDS, history)
        return history

    async def _fetch(
        self,
        *,
        natural_key: str,
        limit: int,
        until: datetime | None,
    ) -> TransportFuelPriceHistory | None:
        connection = _transport_connection(self.settings)
        if connection is None:
            return None
        base_url, headers = connection
        params: dict[str, str | int] = {"limit": limit}
        if until is not None:
            params["until"] = until.isoformat()
        path = EXPORT_PATH_FUEL_STATION_PRICE_HISTORY.format(
            natural_key=quote(natural_key, safe="")
        )
        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                timeout=transport_http_timeout(self.settings),
            ) as client:
                response = await client.get(path, params=params)
            if response.status_code != 200:
                _LOG.warning(
                    "transport 가격 이력 %s: HTTP %s", natural_key, response.status_code
                )
                return None
            return parse_fuel_price_history(response.json(), natural_key=natural_key)
        except (httpx.HTTPError, ValueError, TransportExportContractError) as exc:
            _LOG.warning("transport 가격 이력 %s 실패: %s", natural_key, type(exc).__name__)
            return None


def history_points(
    history: TransportFuelPriceHistory,
    *,
    dataset: FeaturePriceDataset,
) -> list[PricePoint]:
    """transport 이력을 price card 점으로 바꾼다. 가격이 빈 행은 버린다."""
    points: list[PricePoint] = []
    for row in history.points:
        if row.price is None:
            continue
        product_key = OPINET_PRODUCT_KEY_MAP.get(row.product_code, row.product_code.lower())
        points.append(
            PricePoint(
                provider_dataset_id=dataset.provider_dataset_id,
                dataset_key=dataset.dataset_key,
                dataset_display_name=dataset.display_name,
                provider=dataset.provider,
                price_domain=PriceDomain.OPINET_GAS_STATION.value,
                product_key=product_key,
                product_name=OPINET_PRODUCT_NAME_KO.get(product_key),
                source_product_key=row.product_code,
                source_product_name=None,
                value_number=row.price,
                unit="KRW/L",
                observed_at=row.observed_at,
                known_at=row.collected_at,
            )
        )
    return points


@dataclass(frozen=True)
class MergedPriceHistory:
    """transport 이력을 합친 card 조각."""

    current: list[PricePoint]
    history: list[PricePoint]
    history_source: HistorySource


async def merge_transport_history(
    reader: TransportPriceHistoryReader | None,
    *,
    datasets: Sequence[FeaturePriceDataset],
    current: list[PricePoint],
    history: list[PricePoint],
    history_limit: int,
    snapshot_observed_at: datetime | None = None,
) -> MergedPriceHistory:
    """latest-only dataset의 history를 transport에서 읽어 card에 합친다.

    - latest-only dataset이 없으면 Map DB 값 그대로(``map``).
    - 있으면 그 dataset의 DB history 행(현재 winner뿐이다)을 transport 이력으로 바꾼다. 하나라도 읽지
      못하면(이력이 없는 dataset 포함) 그 dataset은 DB 행을 두고 ``unavailable``이다.
    - snapshot(``snapshot_observed_at``)이면 transport 이력을 그 시각까지 읽고 current도 그 이력에서 고른다
      (유종마다 가장 늦은 점). knowledge-time cutoff는 transport 이력에 적용할 수 없다(ADR-114).
    """
    if not datasets:
        return MergedPriceHistory(current=current, history=history, history_source="map")
    replaced: dict[int, list[PricePoint]] = {}
    unavailable = False
    for dataset in datasets:
        if (dataset.provider, dataset.dataset_key) not in TRANSPORT_HISTORY_DATASETS:
            unavailable = True
            continue
        if reader is None or dataset.natural_key is None:
            unavailable = True
            continue
        fetched = await reader.fuel_price_history(
            natural_key=dataset.natural_key,
            limit=history_limit,
            until=snapshot_observed_at,
        )
        if fetched is None:
            unavailable = True
            continue
        replaced[dataset.provider_dataset_id] = history_points(fetched, dataset=dataset)
    if not replaced:
        return MergedPriceHistory(current=current, history=history, history_source="unavailable")
    merged_history = [
        point for point in history if point.provider_dataset_id not in replaced
    ] + [point for points in replaced.values() for point in points]
    merged_history.sort(
        key=lambda point: (point.observed_at, point.known_at), reverse=True
    )
    merged_current = current
    if snapshot_observed_at is not None:
        latest: dict[tuple[int, str, str], PricePoint] = {}
        for points in replaced.values():
            for point in points:
                key = (point.provider_dataset_id, point.price_domain, point.product_key)
                if key not in latest or point.observed_at > latest[key].observed_at:
                    latest[key] = point
        merged_current = sort_current_points(
            [point for point in current if point.provider_dataset_id not in replaced]
            + list(latest.values())
        )
    return MergedPriceHistory(
        current=merged_current,
        history=merged_history[:history_limit],
        history_source="unavailable" if unavailable else "kor_travel_transport",
    )
