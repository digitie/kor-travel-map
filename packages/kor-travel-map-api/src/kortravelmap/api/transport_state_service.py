"""``kortravelmap.api.transport_state_service`` — Valkey 상태 store 의존성과 가격 추이 프록시
(ADR-114).

- :func:`get_state_store` — API 프로세스 하나에 store 하나(connection pool 핸들). ``db.py``의
  engine singleton과 같은 부류다(데이터 캐시가 아니다). Valkey URL이 없으면 503이다 — 나머지 Map
  표면과 ``/ops/health-deep``은 Valkey를 보지 않는다(ADR-114 D6).
- :func:`fetch_price_history` — transport T4
  ``/v1/service/exports/fuel-stations/{station_key}/price-history``를 요청 시 한 페이지씩 읽는다.
  어떤 실패도 예외로 올리지 않고 ``unavailable``과 이유로 돌려준다 — 현재가는 그대로 주고 추이만
  "없음"이다(ADR-114 결정 4). cursor는 불투명하게 그대로 전하고, transport 409(수집 revision
  변경·cursor 만료)는 ``cursor_expired``(누적한 페이지를 버리고 cursor 없이 처음부터)다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import quote, urlsplit

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
    "upstream_unsupported",
    "cursor_expired",
    "request_rejected",
    "upstream_timeout",
    "upstream_unavailable",
    "upstream_rejected",
    "upstream_contract",
]
"""``history.status=unavailable``의 이유(값 하나에 원인 하나).

- ``disabled``·``not_configured``: Map 설정 — transport를 부르지 않았다.
- ``upstream_not_found``: transport 404(없는 주유소 키·옛 버전·토큰·peer fence).
- ``upstream_unsupported``: transport 501(이력을 저장하지 않는 대상).
- ``cursor_expired``: transport 409 — cursor를 보냈는데 수집 revision이 바뀌었거나 cursor(15분)가
  만료됐다. 이미 받은 페이지를 버리고 cursor 없이 첫 페이지부터 다시 읽는다.
- ``request_rejected``: transport 422 — 조회 창(366일 초과·미래 ``until``)·변조/다른 필터의 cursor.
- ``upstream_timeout``: 연결·읽기 timeout.
- ``upstream_unavailable``: 5xx(503 = 성공한 수집 근거 없음)·그 밖의 연결 실패.
- ``upstream_rejected``: 그 밖의 비-200(예: cursor 없이 받은 409·그 밖의 4xx).
- ``upstream_contract``: 200 본문이 계약과 다르다(다른 주유소의 ``station_key`` 포함).
"""


@dataclass(frozen=True, slots=True)
class PriceHistoryOutcome:
    history: TransportFuelPriceHistory | None
    reason: PriceHistoryUnavailableReason | None


def _transport_connection(settings: KorTravelMapSettings) -> tuple[str, dict[str, str]] | None:
    """base URL과 인증 header. 비었거나 형식이 틀리면 ``None``(빈 env도 미설정이다)."""
    base_url = (settings.kor_travel_transport_base_url or "").strip()
    token = settings.kor_travel_transport_service_token
    secret = token.get_secret_value().strip() if token is not None else ""
    if not base_url or not secret or not secret.isascii():
        return None
    try:
        parts = urlsplit(base_url)
        host = parts.hostname
        _ = parts.port  # 숫자가 아닌 port는 ValueError
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not host:
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
    station_key: str,
    *,
    params: Mapping[str, str],
    transport: httpx.AsyncBaseTransport | None = None,
) -> PriceHistoryOutcome:
    """transport에서 가격 이력 한 페이지를 읽는다. 실패는 이유와 함께 ``history=None``으로 돌려준다.

    ``station_key``는 Valkey 주유소 값의 ``natural_key``(transport station_key)다. ``params``는
    :func:`price_history_params`가 만든 transport 질의다.
    """
    if not settings.transport_price_history_enabled:
        return PriceHistoryOutcome(history=None, reason="disabled")
    connection = _transport_connection(settings)
    if connection is None:
        return PriceHistoryOutcome(history=None, reason="not_configured")
    base_url, headers = connection
    if station_key in {"", ".", ".."} or "/" in station_key:
        # 경로 정규화로 다른 transport route를 가리키게 되는 키는 보내지 않는다.
        return PriceHistoryOutcome(history=None, reason="upstream_contract")
    path = EXPORT_PATH_FUEL_STATION_PRICE_HISTORY.format(station_key=quote(station_key, safe=""))
    try:
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=transport_http_timeout(settings),
            headers=headers,
            transport=transport,
        ) as client:
            response = await client.get(path, params=dict(params))
    except httpx.TimeoutException as exc:
        _LOGGER.info("transport 가격 이력 timeout: %s", type(exc).__name__)
        return PriceHistoryOutcome(history=None, reason="upstream_timeout")
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
    if response.status_code == 501:
        return PriceHistoryOutcome(history=None, reason="upstream_unsupported")
    if response.status_code == 409 and "cursor" in params:
        # 수집 revision 변경·cursor 만료 — 소비자가 처음부터 다시 읽어야 한다(정상 신호).
        return PriceHistoryOutcome(history=None, reason="cursor_expired")
    if response.status_code == 422:
        _LOGGER.info("transport 가격 이력 요청 거부(422): 조회 창 또는 cursor")
        return PriceHistoryOutcome(history=None, reason="request_rejected")
    if response.status_code >= 500:
        return PriceHistoryOutcome(history=None, reason="upstream_unavailable")
    if response.status_code != 200:
        _LOGGER.warning("transport 가격 이력이 %d다.", response.status_code)
        return PriceHistoryOutcome(history=None, reason="upstream_rejected")
    try:
        history = parse_fuel_price_history(response.json(), station_key=station_key)
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
    cursor: str | None = None,
) -> dict[str, str]:
    """Map 공개 인자 → transport T4 질의 인자.

    ``product_code``→``product``, ``since``→``from``, ``until``→``to``(timezone이 있는 ISO-8601),
    ``limit``은 한 페이지 전체 행 수(유종 합계)로 그대로, ``cursor``는 불투명하게 그대로 보낸다.
    """
    params = {"limit": str(limit)}
    if product_code:
        params["product"] = product_code
    if since is not None:
        params["from"] = since.isoformat()
    if until is not None:
        params["to"] = until.isoformat()
    if cursor is not None:
        params["cursor"] = cursor
    return params
