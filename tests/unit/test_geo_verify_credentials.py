"""`verify_credentials()`가 "키가 먹히는가"를 실제로 가르는지.

`preflight()`는 형태만 본다 — 다른 서비스의 키를 넣어도 통과한다. 2026-08-13 prod
사고가 정확히 그것이었다(VWorld 키가 geo 키 자리에 결선돼 geo가 401로 거부했고, 정/역
지오코딩이 전부 실패하는 동안 preflight는 초록이었다).

네트워크 없이 돈다. 주입된 클라이언트를 대역으로 바꿔 응답을 만든다 — 이 설계 자체가
`geocoding.py`가 httpx를 런타임 의존으로 갖지 않는 이유이기도 하다(ADR-002/006/044).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from kortravelmap.core.exceptions import GeoAuthNotConfiguredError, GeoRequestError
from kortravelmap.geocoding import KorTravelGeoRestClient

pytestmark = pytest.mark.unit


class _StubClient:
    """주입되는 ``httpx.AsyncClient`` 대역. 정해진 응답 하나만 돌려준다."""

    def __init__(self, response: httpx.Response | Exception) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"path": path, **kwargs})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _resp(status: int, payload: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=payload if payload is not None else {},
        request=httpx.Request("POST", "http://geo.invalid/v2/reverse"),
    )


def _client(response: httpx.Response | Exception, *, key: str = "valid-key") -> tuple[
    KorTravelGeoRestClient, _StubClient
]:
    stub = _StubClient(response)
    client = KorTravelGeoRestClient(
        stub,  # type: ignore[arg-type]
        base_path="/v2",
        api_key=SecretStr(key),
    )
    return client, stub


async def test_accepts_a_key_geo_does_not_reject() -> None:
    client, stub = _client(_resp(200, {"result": None}))
    await client.verify_credentials()  # 던지지 않으면 통과
    assert len(stub.calls) == 1
    assert stub.calls[0]["path"].endswith("/reverse")


async def test_rejects_a_wrong_service_key_401() -> None:
    """geo가 401 ``E0401``로 거부하면 fail-close.

    2026-08-13 사고의 실제 응답 형태다.
    """
    client, _ = _client(_resp(401, {"error": {"code": "E0401"}}))
    with pytest.raises(GeoAuthNotConfiguredError, match="거부"):
        await client.verify_credentials()


async def test_rejects_a_wrong_service_key_400_e0100() -> None:
    client, _ = _client(_resp(400, {"error": {"code": "E0100", "field": "key"}}))
    with pytest.raises(GeoAuthNotConfiguredError, match="거부"):
        await client.verify_credentials()


async def test_other_4xx_is_not_a_credential_failure() -> None:
    """키 거부가 아닌 4xx는 통과시킨다.

    이 메서드가 답하는 질문은 "이 키가 먹히는가" 하나다. 좌표가 범위를 벗어났다거나
    하는 요청 오류를 credential 실패로 보면 **틀린 이유로 기동을 막는다.**
    """
    client, _ = _client(_resp(400, {"error": {"code": "E0200", "field": "lon"}}))
    await client.verify_credentials()


async def test_5xx_is_inconclusive_not_a_credential_failure() -> None:
    """geo가 아플 때 "키가 틀렸다"고 말하면 안 된다."""
    client, _ = _client(_resp(503))
    with pytest.raises(GeoRequestError):
        await client.verify_credentials()


async def test_transport_failure_is_inconclusive() -> None:
    """도달 불가는 판정 불가다 — 호출자가 삼킬지 정한다.

    geo는 별도 stack이라 그쪽 지연이 map 부팅 교착이 되면 안 된다.
    """
    client, _ = _client(httpx.ConnectError("unreachable"))
    with pytest.raises(GeoRequestError):
        await client.verify_credentials()


async def test_missing_key_fails_before_any_network_call() -> None:
    """키가 아예 없으면 네트워크를 쓰지 않고 즉시 실패한다."""
    stub = _StubClient(_resp(200))
    client = KorTravelGeoRestClient(
        stub,  # type: ignore[arg-type]
        base_path="/v2",
        api_key=None,
        require_auth=False,
    )
    with pytest.raises(GeoAuthNotConfiguredError):
        await client.verify_credentials()
    assert stub.calls == []


async def test_the_probe_carries_the_api_key_header() -> None:
    """키를 보내지 않으면 geo가 거부할 수 없고, 검사가 늘 통과한다.

    즉 헤더가 빠지면 이 검사기는 **무엇도 검사하지 않으면서 초록**이 된다.
    """
    client, stub = _client(_resp(200))
    await client.verify_credentials()
    headers = stub.calls[0].get("headers") or {}
    assert headers.get("X-KTG-API-Key") == "valid-key"
