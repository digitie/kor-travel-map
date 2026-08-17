"""기동 시 geo 자격증명 검증 결선(T-VN-H46C).

메서드만 있고 부르는 곳이 없으면 아무것도 지키지 못한다. 여기서 보는 것은 **결선**이다 —
플래그가 꺼져 있으면 안 부르고, 켜져 있으면 부르고, 판정이 비대칭인지.

네트워크는 쓰지 않는다. `httpx.AsyncClient`를 대역으로 바꿔 응답을 만든다.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from kortravelmap.api.app import _verify_kor_travel_geo_credentials
from kortravelmap.core.exceptions import GeoAuthNotConfiguredError
from kortravelmap.settings import KorTravelMapSettings

pytestmark = pytest.mark.unit


class _StubAsyncClient:
    """`httpx.AsyncClient` 대역. 생성 인자를 기록하고 정해진 응답만 돌려준다."""

    instances: list[_StubAsyncClient] = []

    def __init__(self, response: httpx.Response | Exception) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        _StubAsyncClient.instances.append(self)

    async def __aenter__(self) -> _StubAsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.closed = True

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


@pytest.fixture(autouse=True)
def _reset_stub_registry() -> None:
    _StubAsyncClient.instances.clear()


def _patch_client(monkeypatch: pytest.MonkeyPatch, response: httpx.Response | Exception) -> None:
    def _factory(**_kwargs: Any) -> _StubAsyncClient:
        return _StubAsyncClient(response)

    monkeypatch.setattr("kortravelmap.api.app.httpx.AsyncClient", _factory)


def _settings(**overrides: Any) -> KorTravelMapSettings:
    base: dict[str, Any] = {
        "kor_travel_geo_preflight_required": True,
        "kor_travel_geo_base_url": SecretStr("http://geo.invalid"),
        "kor_travel_geo_api_key": SecretStr("valid-key"),
    }
    base.update(overrides)
    return KorTravelMapSettings.model_construct(**base)


async def test_flag_off_makes_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """기본값(False)에서는 네트워크를 아예 쓰지 않는다.

    라이브러리 단위 테스트가 이 경로로 새어 나가면 안 된다.
    """
    _patch_client(monkeypatch, _resp(200))
    await _verify_kor_travel_geo_credentials(
        _settings(kor_travel_geo_preflight_required=False)
    )
    assert _StubAsyncClient.instances == []


async def test_missing_base_url_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    """지오코딩 보강이 비활성이면 검사할 대상이 없다."""
    _patch_client(monkeypatch, _resp(200))
    await _verify_kor_travel_geo_credentials(_settings(kor_travel_geo_base_url=None))
    assert _StubAsyncClient.instances == []


async def test_accepted_key_starts_up(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, _resp(200, {"result": None}))
    await _verify_kor_travel_geo_credentials(_settings())
    assert len(_StubAsyncClient.instances) == 1
    stub = _StubAsyncClient.instances[0]
    assert len(stub.calls) == 1
    assert stub.closed, "client 수명을 닫지 않으면 연결이 샌다"


async def test_rejected_key_blocks_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """키 거부는 fail-close.

    그 키로는 어떤 지오코딩도 성공하지 못한다. 그대로 뜨면 정/역지오코딩이 전부
    실패하는 서비스가 healthy로 보인다 — 2026-08-13 prod 사고가 그 모양이었다.
    """
    _patch_client(monkeypatch, _resp(401, {"error": {"code": "E0401"}}))
    with pytest.raises(GeoAuthNotConfiguredError):
        await _verify_kor_travel_geo_credentials(_settings())


async def test_unreachable_geo_does_not_block_startup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """도달 불가는 fail-open.

    geo는 별도 stack이라 그쪽 지연이 map 전체의 부팅 교착이 되면 안 된다.
    다만 **조용히 넘어가면 안 된다** — 경고가 남아야 한다.
    """
    _patch_client(monkeypatch, httpx.ConnectError("unreachable"))
    with caplog.at_level("WARNING"):
        await _verify_kor_travel_geo_credentials(_settings())
    assert any("kor-travel-geo" in record.message for record in caplog.records)


async def test_geo_5xx_does_not_block_startup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """geo가 아플 때 '키가 틀렸다'고 말하며 기동을 막으면 안 된다."""
    _patch_client(monkeypatch, _resp(503))
    with caplog.at_level("WARNING"):
        await _verify_kor_travel_geo_credentials(_settings())
    assert any("kor-travel-geo" in record.message for record in caplog.records)
