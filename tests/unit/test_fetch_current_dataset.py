"""run-scoped 현재 토큰 팩토리 ``fetch_current_dataset``·불일치 판정 (ADR-109 결정 2, T-GR-02).

실패는 run을 멈추지 않는다 — None + WARNING **정확히 1건**. 지문 없는 릴리스(``data_token`` None)는
geo가 답한 것이라 경고 없이 그대로 돌려준다.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from kortravelmap.dto.geo_dataset import DatasetRef
from kortravelmap.geocoding import (
    KorTravelGeoRestClient,
    fetch_current_dataset,
    geo_dataset_mismatch,
)

pytestmark = pytest.mark.unit

VERSION = "dv1-" + "a" * 32
DATA = "dd1-" + "b" * 32
OTHER = "dd1-" + "c" * 32


def _client(handler: Any) -> tuple[KorTravelGeoRestClient, httpx.AsyncClient]:
    http = httpx.AsyncClient(base_url="http://geo.test", transport=httpx.MockTransport(handler))
    return KorTravelGeoRestClient(http, api_key=SecretStr("k" * 16)), http


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and record.name == "kortravelmap.geocoding"
    ]


async def _run(handler: Any, caplog: pytest.LogCaptureFixture) -> DatasetRef | None:
    client, http = _client(handler)
    try:
        with caplog.at_level(logging.WARNING, logger="kortravelmap.geocoding"):
            return await fetch_current_dataset(client)
    finally:
        await http.aclose()


async def test_success_returns_ref_without_warning(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/dataset/version"
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "available": True,
                "current": {"version_token": VERSION, "data_token": DATA},
            },
        )

    assert await _run(handler, caplog) == DatasetRef(version_token=VERSION, data_token=DATA)
    assert _warnings(caplog) == []


async def test_release_without_fingerprint_is_returned_without_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "OK", "available": True, "current": {"version_token": VERSION}}
        )

    assert await _run(handler, caplog) == DatasetRef(version_token=VERSION, data_token=None)
    assert _warnings(caplog) == []


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("down", request=request)),
        lambda request: httpx.Response(503, json={"status": "ERROR"}),
        lambda request: httpx.Response(401, json={"error": {"code": "E0401"}}),
        lambda request: httpx.Response(200, json={"status": "OK", "available": "yes"}),
        lambda request: httpx.Response(200, json={"status": "OK", "available": False}),
    ],
    ids=["transport", "http-5xx", "key-rejected", "contract", "unavailable"],
)
async def test_failure_or_unavailable_is_none_with_exactly_one_warning(
    handler: Any, caplog: pytest.LogCaptureFixture
) -> None:
    assert await _run(handler, caplog) is None
    assert len(_warnings(caplog)) == 1


async def test_no_client_is_none_with_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="kortravelmap.geocoding"):
        assert await fetch_current_dataset(None) is None
    assert len(_warnings(caplog)) == 1


@pytest.mark.parametrize(
    ("current", "observed", "expected"),
    [
        (DatasetRef(version_token=VERSION, data_token=DATA), [DATA], False),
        (DatasetRef(version_token=VERSION, data_token=DATA), [], False),
        (DatasetRef(version_token=VERSION, data_token=DATA), [DATA, OTHER], True),
        (DatasetRef(version_token=VERSION, data_token=None), [OTHER], False),
        (None, [OTHER], False),
    ],
)
def test_geo_dataset_mismatch(
    current: DatasetRef | None, observed: list[str], expected: bool
) -> None:
    assert geo_dataset_mismatch(current, observed) is expected
