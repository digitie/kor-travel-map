"""run-scoped geo 입력 — `kor_travel_geo_dataset` resource와 적재 메타(ADR-109, T-GR-02)."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from dagster import build_init_resource_context
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied
from kortravelmap.geocoding import (
    GeoCallStats,
    KorTravelGeoRestClient,
    kor_travel_geo_reverse_geocoder,
)
from pydantic import SecretStr

from kortravelmap.dagster import assets, resources
from kortravelmap.dagster.etl import geo_run_metadata

VERSION = "dv1-" + "a" * 32
DATA = "dd1-" + "b" * 32
OTHER = "dd1-" + "c" * 32
CURRENT = DatasetRef(version_token=VERSION, data_token=DATA)
_REVERSE = GeoApplied(reverse=True, geocode=False)
_NONE = GeoApplied(reverse=False, geocode=False)


class _ListLog:
    """``context.log`` 대역 — 받은 경고를 모은다."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, message: str, *args: object) -> None:
        self.warnings.append(message % args if args else message)


def test_unwired_path_emits_no_geo_metadata() -> None:
    log = _ListLog()
    assert geo_run_metadata(None, CURRENT, GeoCallStats(), log=log) == {}  # type: ignore[arg-type]


def test_matching_tokens_record_signal_and_token() -> None:
    stats = GeoCallStats()
    stats.observe_dataset(CURRENT)
    log = _ListLog()
    metadata = geo_run_metadata(_REVERSE, CURRENT, stats, log=log)  # type: ignore[arg-type]
    assert metadata == {
        "geo_applied_reverse": True,
        "geo_applied_geocode": False,
        "geo_data_token": DATA,
        "geo_dataset_mismatch": False,
    }
    assert log.warnings == []


def test_observed_other_token_is_mismatch_with_one_warning() -> None:
    stats = GeoCallStats()
    stats.observe_dataset(CURRENT)
    stats.observe_dataset(DatasetRef(version_token=VERSION, data_token=OTHER))
    log = _ListLog()
    metadata = geo_run_metadata(_REVERSE, CURRENT, stats, log=log)  # type: ignore[arg-type]
    assert metadata["geo_dataset_mismatch"] is True
    assert len(log.warnings) == 1


def test_no_current_token_is_never_mismatch() -> None:
    stats = GeoCallStats()
    stats.observe_dataset(DatasetRef(version_token=VERSION, data_token=OTHER))
    metadata = geo_run_metadata(_REVERSE, None, stats, log=_ListLog())  # type: ignore[arg-type]
    assert metadata["geo_dataset_mismatch"] is False
    assert metadata["geo_data_token"] == "none"


def _dataset_handler(seen: list[str]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "available": True,
                "current": {"version_token": VERSION, "data_token": DATA},
            },
        )

    return handler


def _patch_geo_http(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    real = httpx.AsyncClient

    def client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setenv("KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL", "http://geo.test")
    monkeypatch.setenv("KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY", "k" * 16)
    monkeypatch.setattr(resources.httpx, "AsyncClient", client_factory)


def test_resource_without_base_url_reads_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL", raising=False)
    handle = resources.kor_travel_geo_dataset_resource.resource_fn(build_init_resource_context())
    assert asyncio.run(handle.current()) is None


def test_resource_reads_lazily_and_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    _patch_geo_http(monkeypatch, _dataset_handler(seen))
    handle = resources.kor_travel_geo_dataset_resource.resource_fn(build_init_resource_context())
    assert seen == []  # 초기화에서는 읽지 않는다

    async def twice() -> tuple[object, object]:
        return await asyncio.gather(handle.current(), handle.current())

    first, second = asyncio.run(twice())
    assert first == second == CURRENT
    assert seen == ["/v2/dataset/version"]


def test_auth_misconfiguration_is_named_in_the_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_geo_http(monkeypatch, _dataset_handler([]))
    monkeypatch.setenv("KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY", "")
    handle = resources.kor_travel_geo_dataset_resource.resource_fn(build_init_resource_context())
    with caplog.at_level(logging.WARNING, logger="kortravelmap.dagster.resources"):
        assert asyncio.run(handle.current()) is None
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(messages) == 1
    assert "API key" in messages[0]
    assert "base URL" not in messages[0]


class _Handle:
    def __init__(self, value: DatasetRef | None) -> None:
        self.value = value
        self.calls = 0

    async def current(self) -> DatasetRef | None:
        self.calls += 1
        return self.value


def _context(**resource_values: object) -> Any:
    return SimpleNamespace(resources=SimpleNamespace(**resource_values), log=_ListLog())


def test_geo_run_inputs_uses_the_real_reverse_geocoder_stats() -> None:
    """실제 역지오코더의 ``stats``가 wrapper까지 간다(속성 이름이 바뀌면 빨강)."""

    stats = GeoCallStats()
    http = httpx.AsyncClient(base_url="http://geo.test")
    client = KorTravelGeoRestClient(http, api_key=SecretStr("k" * 16), stats=stats)
    handle = _Handle(CURRENT)
    context = _context(
        reverse_geocoder=kor_travel_geo_reverse_geocoder(client),
        kor_travel_geo_dataset=handle,
    )
    try:
        inputs = asyncio.run(assets._geo_run_inputs(context, _REVERSE))
    finally:
        asyncio.run(http.aclose())
    assert inputs["geo_stats"] is stats
    assert inputs["current_dataset"] == CURRENT
    assert handle.calls == 1


def test_geo_run_inputs_skips_the_fetch_without_geo() -> None:
    handle = _Handle(CURRENT)
    inputs = asyncio.run(assets._geo_run_inputs(_context(kor_travel_geo_dataset=handle), _NONE))
    assert handle.calls == 0
    assert inputs["current_dataset"] is None
    assert inputs["geo_stats"] is None


def test_geo_run_inputs_warns_when_the_resource_is_not_wired() -> None:
    context = _context(reverse_geocoder=None)
    inputs = asyncio.run(assets._geo_run_inputs(context, _REVERSE))
    assert inputs["current_dataset"] is None
    assert len(context.log.warnings) == 1
    assert "배선" in context.log.warnings[0]
