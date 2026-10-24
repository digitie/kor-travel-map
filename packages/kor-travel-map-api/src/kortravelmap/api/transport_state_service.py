"""``kortravelmap.api.transport_state_service`` — Valkey 상태 store 의존성과 가격 추이 프록시
(ADR-114).

- :func:`get_state_store` — API 프로세스 하나에 store 하나(connection pool 핸들). ``db.py``의
  engine singleton과 같은 부류다(데이터 캐시가 아니다). Valkey URL이 없으면 503이다 — 나머지 Map
  표면과 ``/ops/health-deep``은 Valkey를 보지 않는다(ADR-114 D6).
- :func:`fetch_price_history` — transport T4
  ``/v1/service/exports/fuel-stations/{station_key}/price-history``를 요청 시 한 페이지씩 읽는다.
  어떤 실패도 예외로 올리지 않고 ``unavailable``과 이유로 돌려준다 — 현재가는 그대로 주고 추이만
  "없음"이다(ADR-114 결정 4). cursor는 불투명하게 그대로 전한다. 예외: cursor를 보낸 요청의
  transport 409(수집 revision 변경·cursor 만료)는 route가 HTTP 409로 바꾼다(누적한 페이지를 버리고
  cursor 없이 처음부터).
"""

from __future__ import annotations

import json
import logging
import zlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
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

__all__ = [
    "MAX_PRICE_HISTORY_BODY_BYTES",
    "MAX_PRICE_HISTORY_PROBLEM_BYTES",
    "PriceHistoryOutcome",
    "PriceHistoryRequest",
    "PriceHistoryUnavailableReason",
    "close_state_store",
    "fetch_price_history",
    "get_state_store",
    "set_state_store_for_test",
    "shared_state_store",
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


def shared_state_store() -> ValkeyStateStore:
    """프로세스 단위 store(transport·weather 표면이 함께 쓴다).

    설정이 없으면 :class:`StateStoreError`.

    이벤트 루프에서만 부른다(아래 async 의존성) — 확인과 대입 사이에 ``await``가 없어 동시 첫 요청이
    client를 둘 만들어 하나를 새게 하지 않는다(sync 의존성은 threadpool에서 돈다).
    """
    global _store
    if _store is None:
        _store = ValkeyStateStore(make_valkey_client(KorTravelMapSettings()))
    return _store


async def get_state_store() -> ValkeyStateStore:
    """FastAPI 의존성(transport 표면) — 프로세스 단위 store. 설정이 없으면 503."""
    try:
        return shared_state_store()
    except StateStoreError as exc:
        raise state_unavailable(str(exc)) from exc


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
    "request_rejected",
    "upstream_no_collection",
    "upstream_timeout",
    "upstream_unavailable",
    "upstream_rejected",
    "upstream_contract",
]
"""``history.status=unavailable``의 이유(값 하나에 원인 하나).

- ``disabled``·``not_configured``: Map 설정 — transport를 부르지 않았다.
- ``upstream_not_found``: transport 404(없는 주유소 키·옛 버전·토큰·peer fence).
- ``upstream_unsupported``: transport 501(이력을 저장하지 않는 대상).
- ``request_rejected``: transport 422 — 조회 창(366일 초과·미래 ``until``)·변조/다른 조건의 cursor.
- ``upstream_no_collection``: transport 503 problem의 ``meta.source_status=failed`` — 성공한
  유가 수집 근거가 아직 없다.
- ``upstream_timeout``: 연결·읽기 timeout.
- ``upstream_unavailable``: 그 밖의 5xx·연결 실패.
- ``upstream_rejected``: 그 밖의 비-200(예: cursor 없이 받은 409·그 밖의 4xx).
- ``upstream_contract``: 200 본문이 계약과 다르다(다른 ``station_key``·요청과 다른 유종이나 창 밖의
  행·유한하지 않은 가격·200 본문의 ``source_status=failed``·JSON이 아니거나 너무 깊은 본문·
  ``MAX_PRICE_HISTORY_BODY_BYTES`` 초과·깨진 gzip·모르는 Content-Encoding 포함).

cursor를 보낸 요청의 transport 409(수집 revision 변경·cursor 만료)는 이유가 아니다 — 응답 전체가
HTTP 409 ``TRANSPORT_PRICE_HISTORY_CURSOR_EXPIRED``다(:attr:`PriceHistoryOutcome.cursor_expired`).
"""

MAX_PRICE_HISTORY_BODY_BYTES = 2 * 1024 * 1024
"""transport 응답 본문(압축 해제 뒤) 상한. 1000행 한 페이지는 약 100 KB다 — 넘으면 계약 위반이다."""

MAX_PRICE_HISTORY_PROBLEM_BYTES = 64 * 1024
"""비-200 본문 중 읽는 것(503 problem의 ``meta.source_status``)의 상한. 넘거나 못 읽으면 본문 없이
상태 코드로만 분류한다."""


@dataclass(frozen=True, slots=True)
class PriceHistoryRequest:
    """Map 공개 인자. :attr:`params`가 transport T4 질의다."""

    product_code: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 200
    cursor: str | None = None

    @property
    def params(self) -> dict[str, str]:
        """``product_code``→``product``, ``since``→``from``, ``until``→``to``(timezone이 있는
        ISO-8601), ``limit``은 한 페이지 전체 행 수(유종 합계), ``cursor``는 불투명하게 그대로.
        """
        params = {"limit": str(self.limit)}
        if self.product_code:
            params["product"] = self.product_code
        if self.since is not None:
            params["from"] = self.since.isoformat()
        if self.until is not None:
            params["to"] = self.until.isoformat()
        if self.cursor is not None:
            params["cursor"] = self.cursor
        return params


@dataclass(frozen=True, slots=True)
class PriceHistoryOutcome:
    history: TransportFuelPriceHistory | None
    reason: PriceHistoryUnavailableReason | None
    cursor_expired: bool = False
    """cursor를 보냈는데 transport가 409였다 — route가 HTTP 409로 바꾼다(처음부터 다시)."""


def _unavailable(reason: PriceHistoryUnavailableReason) -> PriceHistoryOutcome:
    return PriceHistoryOutcome(history=None, reason=reason)


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


class _BodyTooLarge(Exception):
    pass


class _BadEncoding(Exception):
    pass


async def _read_capped(response: httpx.Response, cap: int) -> bytes:
    """본문을 ``cap`` bytes까지만 읽는다 — 원문(전송) 크기와 압축 해제 뒤 크기 모두.

    httpx의 ``aiter_bytes``는 받은 조각을 통째로 풀어 내놓으므로(작은 gzip 조각이 수십 MB로
    풀린다) 상한이 무력하다. 여기서는 원문을 ``aiter_raw``로 상한까지 모은 뒤, gzip이면 출력 상한을
    건 ``zlib.decompressobj``로 푼다. 요청은 ``Accept-Encoding: identity``라 정상이면 gzip이 오지
    않는다. 깨진·잘린 gzip과 모르는 인코딩은 :class:`_BadEncoding`, 상한 초과는
    :class:`_BodyTooLarge`다.
    """
    encoding = response.headers.get("content-encoding", "").strip().lower()
    if encoding not in {"", "identity", "gzip"}:
        raise _BadEncoding
    declared = response.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > cap:
        raise _BodyTooLarge
    raw = bytearray()
    async for chunk in response.aiter_raw():
        if len(raw) + len(chunk) > cap:
            raise _BodyTooLarge
        raw += chunk
    if encoding != "gzip":
        return bytes(raw)
    decoder = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    try:
        decoded = decoder.decompress(bytes(raw), cap + 1)
    except zlib.error as exc:
        raise _BadEncoding from exc
    if len(decoded) > cap or decoder.unconsumed_tail:
        raise _BodyTooLarge
    if not decoder.eof:
        raise _BadEncoding  # 잘린 gzip
    return decoded


def _reject_constant(name: str) -> object:
    raise ValueError(f"JSON 상수 {name}은 받지 않는다.")


def _load_json(body: bytes) -> object:
    """엄격 JSON — ``NaN``·``Infinity`` 상수 거부.

    깊은 중첩의 ``RecursionError``는 호출자가 잡는다.
    """
    return json.loads(body, parse_constant=_reject_constant)


def _is_no_collection_problem(body: bytes) -> bool:
    """transport 503 problem+json의 ``meta.source_status=failed``(성공한 수집 근거 없음)."""
    try:
        payload = _load_json(body)
    except (ValueError, RecursionError):
        return False
    if not isinstance(payload, dict):
        return False
    meta = payload.get("meta")
    return isinstance(meta, dict) and meta.get("source_status") == "failed"


async def fetch_price_history(
    settings: KorTravelMapSettings,
    station_key: str,
    *,
    request: PriceHistoryRequest,
    transport: httpx.AsyncBaseTransport | None = None,
) -> PriceHistoryOutcome:
    """transport에서 가격 이력 한 페이지를 읽는다. 실패는 이유와 함께 ``history=None``으로 돌려준다.

    ``station_key``는 Valkey 주유소 값의 ``natural_key``(transport station_key)다. 예외를 올리지
    않는다 — cursor 만료도 :attr:`PriceHistoryOutcome.cursor_expired`로 돌려준다.
    """
    if not settings.transport_price_history_enabled:
        return _unavailable("disabled")
    connection = _transport_connection(settings)
    if connection is None:
        return _unavailable("not_configured")
    base_url, headers = connection
    if station_key in {"", ".", ".."} or "/" in station_key:
        # 경로 정규화로 다른 transport route를 가리키게 되는 키는 보내지 않는다.
        return _unavailable("upstream_contract")
    path = EXPORT_PATH_FUEL_STATION_PRICE_HISTORY.format(station_key=quote(station_key, safe=""))
    try:
        async with (
            httpx.AsyncClient(
                base_url=base_url,
                timeout=transport_http_timeout(settings),
                headers=headers,
                transport=transport,
            ) as client,
            client.stream(
                "GET",
                path,
                params=request.params,
                # 한 페이지는 약 100 KB다 — 압축을 받지 않아 본문 상한을 원문 크기로 잰다.
                headers={"Accept-Encoding": "identity"},
            ) as response,
        ):
            # 상태 코드를 먼저 본다. 200만 본문 전체를 읽고, 503만 problem의 meta를 작은 상한으로
            # 읽는다 — 큰 오류 본문도 상태 코드로 분류된다(cursor 409 신호 포함).
            status_code = response.status_code
            body = b""
            if status_code == 200:
                body = await _read_capped(response, MAX_PRICE_HISTORY_BODY_BYTES)
            elif status_code == 503:
                try:
                    body = await _read_capped(response, MAX_PRICE_HISTORY_PROBLEM_BYTES)
                except (_BodyTooLarge, _BadEncoding, httpx.DecodingError):
                    body = b""
    except _BodyTooLarge:
        _LOGGER.warning(
            "transport 가격 이력 본문이 %d bytes를 넘는다.", MAX_PRICE_HISTORY_BODY_BYTES
        )
        return _unavailable("upstream_contract")
    except (_BadEncoding, httpx.DecodingError) as exc:
        # 깨진·잘린 gzip·모르는 Content-Encoding — 연결 문제가 아니라 본문이 계약과 다르다.
        _LOGGER.warning("transport 가격 이력 본문 인코딩 오류: %s", type(exc).__name__)
        return _unavailable("upstream_contract")
    except httpx.TimeoutException as exc:
        _LOGGER.info("transport 가격 이력 timeout: %s", type(exc).__name__)
        return _unavailable("upstream_timeout")
    except httpx.HTTPError as exc:
        _LOGGER.info("transport 가격 이력 요청 실패: %s", type(exc).__name__)
        return _unavailable("upstream_unavailable")
    except (httpx.InvalidURL, ValueError) as exc:
        # 주소·토큰 형식이 틀렸다(InvalidURL은 HTTPError가 아니다, 비ASCII 토큰은 ValueError).
        _LOGGER.warning("transport 가격 이력 설정이 올바르지 않다: %s", type(exc).__name__)
        return _unavailable("not_configured")
    if status_code == 404:
        # 없는 주유소 키·옛 transport(경로 없음)·토큰 불일치·peer fence 중 하나다 — 설정 문제일 수
        # 있어 경고한다.
        _LOGGER.warning(
            "transport 가격 이력이 404다 — 키가 없거나, 경로가 없는 버전이거나, 토큰·접속 주소가 "
            "맞지 않는다."
        )
        return _unavailable("upstream_not_found")
    if status_code == 501:
        return _unavailable("upstream_unsupported")
    if status_code == 409 and request.cursor is not None:
        # 수집 revision 변경·cursor 만료 — 소비자가 처음부터 다시 읽어야 한다.
        return PriceHistoryOutcome(history=None, reason=None, cursor_expired=True)
    if status_code == 422:
        _LOGGER.info("transport 가격 이력 요청 거부(422): 조회 창 또는 cursor")
        return _unavailable("request_rejected")
    if status_code == 503 and _is_no_collection_problem(body):
        return _unavailable("upstream_no_collection")
    if status_code >= 500:
        return _unavailable("upstream_unavailable")
    if status_code != 200:
        _LOGGER.warning("transport 가격 이력이 %d다.", status_code)
        return _unavailable("upstream_rejected")
    try:
        history = parse_fuel_price_history(
            _load_json(body),
            station_key=station_key,
            product_code=request.product_code,
            observed_from=request.since,
            observed_to=request.until,
        )
    except (ValueError, RecursionError, TransportExportContractError) as exc:
        # UnicodeDecodeError·JSONDecodeError는 ValueError다. 깊은 중첩은 RecursionError다.
        _LOGGER.warning("transport 가격 이력 계약 위반(%s): %s", type(exc).__name__, exc)
        return _unavailable("upstream_contract")
    return PriceHistoryOutcome(history=history, reason=None)
