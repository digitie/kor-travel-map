"""transport client connect/read timeout 분리(ADR-110 결정 3, T-MAP-02).

(1) 팩토리가 설정 두 필드를 옮기는지, (2) 실제 export fetcher가 무응답 호스트에서 connect 상한
안에 실패하는지 본다. (2)는 accept 큐를 미리 채운 로컬 ``listen(0)`` 서버로 SYN 드롭을 만든다
(전제를 먼저 확인한다 — 전제가 안 서면 read 상한까지 기다리는 '우연한 초록'이 된다). Linux 전제.
"""

from __future__ import annotations

import socket
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress

import httpx
import pytest
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

from kortravelmap.dagster import upstream_retry
from kortravelmap.dagster.provider_fetchers import (
    fetch_transport_airports,
    transport_http_timeout,
)

CONNECT = 0.5
READ = 25.0


def test_transport_http_timeout_carries_both_settings_fields() -> None:
    settings = KorTravelMapSettings(
        kor_travel_transport_timeout_seconds=17.0,
        kor_travel_transport_connect_timeout_seconds=1.5,
    )
    timeout = transport_http_timeout(settings)
    assert timeout.connect == 1.5
    assert timeout.read == timeout.write == timeout.pool == 17.0


def test_transport_connect_timeout_defaults() -> None:
    timeout = transport_http_timeout(KorTravelMapSettings())
    assert timeout.connect == 2.0
    assert timeout.read == 30.0


@contextmanager
def _unresponsive_port() -> Iterator[int]:
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
async def test_unresponsive_transport_fails_within_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 재시도 1회로 — 재지는 것은 시도 하나의 connect 상한이다(재시도·backoff는 별도 규약).
    monkeypatch.setattr(upstream_retry, "DEFAULT_UPSTREAM_ATTEMPTS", 1)
    with _unresponsive_port() as port:
        settings = KorTravelMapSettings(
            kor_travel_transport_base_url=f"http://127.0.0.1:{port}",
            kor_travel_transport_service_token=SecretStr("t" * 40),
            kor_travel_transport_timeout_seconds=READ,
            kor_travel_transport_connect_timeout_seconds=CONNECT,
        )
        started = time.monotonic()
        with pytest.raises(httpx.ConnectTimeout):
            async for _ in fetch_transport_airports(settings):
                pass
        elapsed = time.monotonic() - started
    # connect 분리가 없으면 read 상한(READ)까지 기다린다.
    assert elapsed < CONNECT + 0.5, elapsed
