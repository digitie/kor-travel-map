"""geo client connect/read timeout 분리(ADR-110 결정 3, T-MAP-02).

(1) 팩토리가 설정 두 필드를 그대로 옮기는지, (2) 무응답 호스트에서 connect 상한 안에 실패하는지를
본다. (2)는 실제 네트워크에 기대지 않는다 — 로컬 ``listen(0)`` 서버의 accept 큐를 미리 채워
SYN이 드롭되게 만들고, 그 전제가 섰는지를 먼저 확인한다(전제가 안 서면 첫 connect가 성공해
read 상한까지 기다리는 '우연한 초록'이 되기 때문). Linux(n150·CI) 전제다.
"""

from __future__ import annotations

import socket
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress

import httpx
import pytest
from pydantic import SecretStr

from kortravelmap.core.exceptions import GeoRequestError
from kortravelmap.geocoding import KorTravelGeoRestClient, geo_http_timeout
from kortravelmap.settings import KorTravelMapSettings

pytestmark = pytest.mark.unit

CONNECT = 0.5
READ = 9.0


def test_geo_http_timeout_carries_both_settings_fields() -> None:
    settings = KorTravelMapSettings(
        kor_travel_geo_timeout_seconds=7.5,
        kor_travel_geo_connect_timeout_seconds=1.25,
    )
    timeout = geo_http_timeout(settings)
    assert timeout.connect == 1.25
    assert timeout.read == timeout.write == timeout.pool == 7.5


def test_geo_connect_timeout_defaults() -> None:
    timeout = geo_http_timeout(KorTravelMapSettings())
    assert timeout.connect == 2.0
    assert timeout.read == 10.0


@contextmanager
def unresponsive_port() -> Iterator[int]:
    """SYN이 드롭되는 로컬 포트 — accept 큐를 먼저 채운 ``listen(0)`` 서버."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    fillers: list[socket.socket] = []
    try:
        server.bind(("127.0.0.1", 0))
        server.listen(0)
        port = int(server.getsockname()[1])
        for _ in range(8):
            filler = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            filler.setblocking(False)
            with suppress(BlockingIOError):
                filler.connect(("127.0.0.1", port))
            fillers.append(filler)
        time.sleep(0.2)
        # 전제: 새 connect가 실제로 매달린다. 성공하면 이 테스트는 아무것도 재지 않는다.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.3)
        try:
            probe.connect(("127.0.0.1", port))
        except TimeoutError:
            pass
        else:
            pytest.fail("accept 큐를 채웠는데 connect가 성공했다 — SYN 드롭 전제가 서지 않는다")
        finally:
            probe.close()
        yield port
    finally:
        for filler in fillers:
            filler.close()
        server.close()


@pytest.mark.skipif(sys.platform != "linux", reason="accept 큐 SYN 드롭은 Linux 동작이다")
async def test_unresponsive_geo_fails_within_connect_timeout() -> None:
    settings = KorTravelMapSettings(
        kor_travel_geo_timeout_seconds=READ,
        kor_travel_geo_connect_timeout_seconds=CONNECT,
    )
    with unresponsive_port() as port:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", timeout=geo_http_timeout(settings)
        ) as http:
            client = KorTravelGeoRestClient(http, api_key=SecretStr("k" * 32))
            started = time.monotonic()
            with pytest.raises(GeoRequestError, match="ConnectTimeout"):
                await client.reverse(x=127.0, y=37.5)
            elapsed = time.monotonic() - started
    # connect 분리가 없으면 read 상한(READ)까지 기다린다.
    assert elapsed < CONNECT + 0.5, elapsed
