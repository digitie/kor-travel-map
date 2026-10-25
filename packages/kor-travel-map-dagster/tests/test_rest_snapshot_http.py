"""정본 HTTP helper의 새 opt-in bounded one-page 경계. MockTransport뿐이며 실제HTTP0."""

import asyncio
import gzip
import hashlib
import json

import httpx
import pytest
from kortravelmap.providers.kor_travel_transport import (
    TransportExportContractError,
    TransportRestArea,
)
from kortravelmap.providers.krex import rest_area_natural_key
from test_transport_fetchers import _settings

from kortravelmap.dagster import provider_fetchers as target
from kortravelmap.dagster.rest_snapshot_observation import UnsupportedRestObservation
from kortravelmap.dagster.upstream_requests import (
    counting_upstream_requests,
    observed_upstream_requests,
)

_REAL = httpx.AsyncClient


class _Chunks(httpx.AsyncByteStream):
    def __init__(self, content, *, delay=0):
        self.content = content
        self.delay = delay
        self.closed = False

    async def __aiter__(self):
        for i in range(0, len(self.content), 31):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield self.content[i : i + 31]

    async def aclose(self):
        self.closed = True


def _payload():
    item = TransportRestArea(
        "pending", "휴게소", "경부선", "상행", None, None, "031-123-4567", None, None, None, {}
    )
    key = rest_area_natural_key(item)
    return {
        "items": [
            {
                "natural_key": key,
                "name": item.name,
                "route_name": item.route_name,
                "direction": item.direction,
                "longitude": None,
                "latitude": None,
                "phone_number": item.phone_number,
                "raw": {},
            }
        ],
        "next_cursor": None,
        "has_more": False,
        "collection": {
            "source": "krex_rest_area",
            "last_success_at": "2026-10-25T00:00:00+00:00",
            "failed": False,
            "stale": False,
        },
    }


def _install(monkeypatch, payload=None, *, raw=None, encoding="identity", delay=0):
    body = json.dumps(_payload() if payload is None else payload).encode() if raw is None else raw
    stream = _Chunks(gzip.compress(body) if encoding == "gzip" else body, delay=delay)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json", "content-encoding": encoding},
            stream=stream,
        )

    monkeypatch.setattr(
        target.httpx,
        "AsyncClient",
        lambda **kw: _REAL(transport=httpx.MockTransport(handler), **kw),
    )
    return body, stream, seen


@pytest.mark.parametrize("encoding", ["identity", "gzip"])
async def test_one_actual_attempt_keeps_complete_decoded_body_hash_metadata_and_no_cursor(
    monkeypatch, encoding
):
    body, stream, seen = _install(monkeypatch, encoding=encoding)
    with counting_upstream_requests():
        value = await target.fetch_transport_rest_area_snapshot(_settings())
        assert observed_upstream_requests() == 1
    assert len(seen) == 1
    assert dict(seen[0].url.params) == {"limit": "256"}
    assert len(value.records) == 1
    assert value.export_window.item_count == 1
    assert value.export_window.body_sha256 == hashlib.sha256(body).hexdigest()
    assert value.export_window.body_bytes == len(body)
    assert value.export_window.captured_at.utcoffset() is not None
    assert stream.closed


@pytest.mark.parametrize(
    "fault",
    [
        "more",
        "cursor",
        "badcursor",
        "missingcursor",
        "empty",
        "257",
        "duplicate",
        "wrongsource",
        "future",
        "naive",
    ],
)
async def test_truncated_or_noncanonical_window_never_becomes_partial_registration_input(
    monkeypatch, fault
):
    p = _payload()
    if fault == "more":
        p.update(has_more=True, next_cursor="next")
    elif fault == "cursor":
        p["next_cursor"] = "next"
    elif fault == "badcursor":
        p["next_cursor"] = 7
    elif fault == "missingcursor":
        del p["next_cursor"]
    elif fault == "empty":
        p["items"] = []
    elif fault == "257":
        p["items"] *= 257
    elif fault == "duplicate":
        p["items"] *= 2
    elif fault == "wrongsource":
        p["collection"]["source"] = "other"
    elif fault == "future":
        p["collection"]["last_success_at"] = "2099-01-01T00:00:00+00:00"
    else:
        p["collection"]["last_success_at"] = "2026-10-25T00:00:00"
    _, stream, _ = _install(monkeypatch, p)
    with pytest.raises((TransportExportContractError, UnsupportedRestObservation)):
        await target.fetch_transport_rest_area_snapshot(_settings())
    assert stream.closed


@pytest.mark.parametrize("fault", ["encoded", "bomb", "truncated", "trailing", "concatenated"])
async def test_response_and_gzip_expansion_are_bounded_and_eof_exact(monkeypatch, fault):
    body = json.dumps(_payload()).encode()
    headers = "identity"
    if fault == "encoded":
        raw = b" " * (2 * 1024 * 1024 + 1)
    elif fault == "bomb":
        raw = gzip.compress(b" " * (2 * 1024 * 1024 + 1))
        headers = "gzip"
    elif fault == "truncated":
        raw = gzip.compress(body)[:-2]
        headers = "gzip"
    elif fault == "trailing":
        raw = gzip.compress(body) + b"other"
        headers = "gzip"
    else:
        raw = gzip.compress(body) + gzip.compress(body)
        headers = "gzip"
    _, stream, seen = _install(monkeypatch, raw=raw)

    # 주어진 raw stream을 다시 압축하지 않고 실제 wire header만 설정한다.
    def handler(request):
        seen.append(request)
        return httpx.Response(200, headers={"content-encoding": headers}, stream=stream)

    monkeypatch.setattr(
        target.httpx,
        "AsyncClient",
        lambda **kw: _REAL(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(TransportExportContractError):
        await target.fetch_transport_rest_area_snapshot(_settings())
    assert stream.closed


async def test_one_total_fetch_deadline_includes_slow_stream_and_closes_response(monkeypatch):
    _, stream, _ = _install(monkeypatch, delay=0.03)
    with pytest.raises(TimeoutError):
        await target.fetch_transport_rest_area_snapshot(
            _settings(kor_travel_transport_timeout_seconds=0.2)
        )
    assert stream.closed
