"""``kortravelmap.api.transport_state_service`` — Valkey 상태 store 의존성과 가격 추이 프록시
(ADR-114).

- :func:`get_state_store` — API 프로세스 하나에 store 하나(connection pool 핸들). ``db.py``의
  engine singleton과 같은 부류다(데이터 캐시가 아니다). Valkey URL이 없으면 503이다 — 나머지 Map
  표면과 ``/ops/health-deep``은 Valkey를 보지 않는다(ADR-114 D6).
- :func:`fetch_price_history` — transport
  ``/v1/service/exports/fuel-stations/{uni_id}/price-history``를 요청 시 그대로 읽는다. 어떤
  실패도 예외로 올리지 않고 ``unavailable``과 이유로 돌려준다 — 현재가는 그대로 주고 추이만
  "없음"이다(ADR-114 결정 4).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status
from kortravelmap.infra.valkey_state import (
    StateStoreError,
    ValkeyStateStore,
    make_valkey_client,
)
from kortravelmap.providers.kor_travel_transport import (
    EXPORT_PATH_FUEL_STATION_PRICE_HISTORY,
    SERVICE_TOKEN_HEADER,
    TransportExportContractError,
    TransportFuelPriceHistory,
    parse_fuel_price_history,
)
from kortravelmap.settings import KorTravelMapSettings

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "PriceHistoryOutcome",
    "PriceHistoryUnavailableReason",
    "close_state_store",
    "fetch_price_history",
    "get_state_store",
    "set_state_store_for_test",
    "state_unavailable",
    "transport_http_timeout",
]

_LOGGER = logging.getLogger(__name__)

_store: ValkeyStateStore | None = None


def state_unavailable(message: str) -> HTTPException:
    """이 표면만의 503(ADR-114 D6)."""
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "TRANSPORT_STATE_UNAVAILABLE", "message": message, "details": {}},
    )


async def get_state_store() -> ValkeyStateStore:
    """FastAPI 의존성 — 프로세스 단위 store. 설정이 없으면 503.

    ``async``라 이벤트 루프에서 돈다 — 확인과 대입 사이에 ``await``가 없어 동시 첫 요청이 client를
    둘 만들어 하나를 새게 하지 않는다(sync 의존성은 threadpool에서 돈다).
    """
    global _store
    if _store is None:
        try:
            _store = ValkeyStateStore(make_valkey_client(KorTravelMapSettings()))
        except StateStoreError as exc:
            raise state_unavailable(str(exc)) from exc
    return _store


def set_state_store_for_test(store: ValkeyStateStore | None) -> None:
    """테스트가 store를 주입하거나(``None``이면) 비운다."""
    global _store
    _store = store


async def close_state_store() -> None:
    """lifespan 종료 때 pool을 닫는다."""
    global _store
    store, _store = _store, None
    if store is not None:
        await store.client.aclose()


# -- 가격 추이 프록시 -------------------------------------------------------------

PriceHistoryUnavailableReason = Literal[
    "disabled",
    "not_configured",
    "upstream_not_found",
    "upstream_unavailable",
    "upstream_rejected",
    "upstream_contract",
]


@dataclass(frozen=True, slots=True)
class PriceHistoryOutcome:
    history: TransportFuelPriceHistory | None
    reason: PriceHistoryUnavailableReason | None


def _transport_connection(settings: KorTravelMapSettings) -> tuple[str, dict[str, str]] | None:
    """base URL과 인증 header. 둘 중 하나라도 비면 ``None``(빈 env도 미설정이다)."""
    base_url = (settings.kor_travel_transport_base_url or "").strip()
    token = settings.kor_travel_transport_service_token
    secret = token.get_secret_value().strip() if token is not None else ""
    if not base_url or not secret:
        return None
    return base_url.rstrip("/"), {SERVICE_TOKEN_HEADER: secret}


def transport_http_timeout(settings: KorTravelMapSettings) -> httpx.Timeout:
    """가격 추이 프록시의 timeout — read는 사용자 요청 경로라 짧게, 연결 수립은 transport 공통
    상한.
    """
    return httpx.Timeout(
        settings.transport_price_history_timeout_seconds,
        connect=settings.kor_travel_transport_connect_timeout_seconds,
    )


async def fetch_price_history(
    settings: KorTravelMapSettings,
    natural_key: str,
    *,
    params: Mapping[str, str],
    transport: httpx.AsyncBaseTransport | None = None,
) -> PriceHistoryOutcome:
    """transport에서 가격 이력을 읽는다. 실패는 이유와 함께 ``history=None``으로 돌려준다."""
    if not settings.transport_price_history_enabled:
        return PriceHistoryOutcome(history=None, reason="disabled")
    connection = _transport_connection(settings)
    if connection is None:
        return PriceHistoryOutcome(history=None, reason="not_configured")
    base_url, headers = connection
    if natural_key in {"", ".", ".."} or "/" in natural_key:
        # 경로 정규화로 다른 transport route를 가리키게 되는 키는 보내지 않는다.
        return PriceHistoryOutcome(history=None, reason="upstream_contract")
    path = EXPORT_PATH_FUEL_STATION_PRICE_HISTORY.format(natural_key=quote(natural_key, safe=""))
    try:
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=transport_http_timeout(settings),
            headers=headers,
            transport=transport,
        ) as client:
            response = await client.get(path, params=dict(params))
    except httpx.HTTPError as exc:
        _LOGGER.info("transport 가격 이력 요청 실패: %s", type(exc).__name__)
        return PriceHistoryOutcome(history=None, reason="upstream_unavailable")
    except (httpx.InvalidURL, ValueError) as exc:
        # 주소·토큰 형식이 틀렸다(InvalidURL은 HTTPError가 아니다, 비ASCII 토큰은 ValueError).
        _LOGGER.warning("transport 가격 이력 설정이 올바르지 않다: %s", type(exc).__name__)
        return PriceHistoryOutcome(history=None, reason="not_configured")
    if response.status_code == 404:
        # 옛 transport(경로 없음)·토큰 불일치·peer fence 셋 중 하나다 — 설정 문제일 수 있어
        # 경고한다.
        _LOGGER.warning(
            "transport 가격 이력이 404다 — 경로가 없는 버전이거나 토큰·접속 주소가 맞지 않는다."
        )
        return PriceHistoryOutcome(history=None, reason="upstream_not_found")
    if response.status_code >= 500:
        return PriceHistoryOutcome(history=None, reason="upstream_unavailable")
    if response.status_code != 200:
        _LOGGER.warning("transport 가격 이력이 %d다.", response.status_code)
        return PriceHistoryOutcome(history=None, reason="upstream_rejected")
    try:
        history = parse_fuel_price_history(response.json(), natural_key=natural_key)
    except (ValueError, TransportExportContractError) as exc:
        _LOGGER.warning("transport 가격 이력 계약 위반: %s", exc)
        return PriceHistoryOutcome(history=None, reason="upstream_contract")
    return PriceHistoryOutcome(history=history, reason=None)


def price_history_params(
    *,
    product_code: str | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
) -> dict[str, str]:
    """transport 질의 인자. 시각은 timezone이 있는 ISO-8601로 보낸다."""
    params = {"limit": str(limit)}
    if product_code:
        params["product_code"] = product_code
    if since is not None:
        params["since"] = since.isoformat()
    if until is not None:
        params["until"] = until.isoformat()
    return params
