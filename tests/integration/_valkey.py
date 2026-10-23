"""통합 테스트용 일회용 Valkey 컨테이너(ADR-114).

이미지는 digest로 고정한다 — n150 Manager의 Map Valkey 서비스(``valkey/valkey:9.0-alpine``)와 같은
digest다. 태그가 움직여 다른 서버 버전으로 초록이 되지 않게 한다. 지속성은 끈다(테스트는 매번
비운다).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

VALKEY_IMAGE = (
    "valkey/valkey:9.0-alpine@sha256:"
    "187679e3bd4036959631e3f03983ab2ba503ab21e6fd0454d508e909db2ee989"
)
VALKEY_PASSWORD = "adr114-test-password"


@contextmanager
def valkey_container() -> Iterator[str]:
    """컨테이너를 띄우고 ``redis://`` URL을 낸다. Docker·testcontainers가 없으면 skip."""
    try:
        from testcontainers.core.container import DockerContainer
    except ImportError:  # pragma: no cover - dev extra 없음
        pytest.skip("testcontainers가 설치되지 않았다.")
    container: Any = (
        DockerContainer(VALKEY_IMAGE)
        .with_command(
            f"valkey-server --requirepass {VALKEY_PASSWORD} --save '' --appendonly no "
            "--maxmemory 64mb --maxmemory-policy noeviction"
        )
        .with_exposed_ports(6379)
    )
    try:
        container.start()
    except Exception as exc:  # pragma: no cover - Docker 없음
        pytest.skip(f"Valkey 컨테이너를 띄우지 못했다: {type(exc).__name__}")
    try:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(6379))
        _wait_ready(host, port)
        yield f"redis://:{VALKEY_PASSWORD}@{host}:{port}/0"
    finally:
        container.stop()


def _wait_ready(host: str, port: int, *, timeout: float = 30.0) -> None:
    import redis

    deadline = time.monotonic() + timeout
    while True:
        try:
            client = redis.Redis(host=host, port=port, password=VALKEY_PASSWORD)
            try:
                if client.ping():
                    return
            finally:
                client.close()
        except redis.RedisError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)
