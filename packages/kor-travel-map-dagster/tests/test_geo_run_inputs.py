"""run-scoped geo 입력 — `kor_travel_geo_dataset` resource와 적재 메타(ADR-109, T-GR-02)."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
from dagster import build_init_resource_context
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied
from kortravelmap.geocoding import GeoCallStats

from kortravelmap.dagster import resources
from kortravelmap.dagster.etl import geo_run_metadata

VERSION = "dv1-" + "a" * 32
DATA = "dd1-" + "b" * 32
OTHER = "dd1-" + "c" * 32
CURRENT = DatasetRef(version_token=VERSION, data_token=DATA)


def _etl_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and record.name == "kortravelmap.dagster.etl"
    ]


def test_unwired_path_emits_no_geo_metadata() -> None:
    assert geo_run_metadata(None, CURRENT, GeoCallStats()) == {}


def test_matching_tokens_record_signal_and_token(caplog: pytest.LogCaptureFixture) -> None:
    stats = GeoCallStats()
    stats.observe_dataset(CURRENT)
    with caplog.at_level(logging.WARNING):
        metadata = geo_run_metadata(GeoApplied(reverse=True, geocode=False), CURRENT, stats)
    assert metadata == {
        "geo_applied_reverse": True,
        "geo_applied_geocode": False,
        "geo_data_token": DATA,
        "geo_dataset_mismatch": False,
    }
    assert _etl_warnings(caplog) == []


def test_observed_other_token_is_mismatch_with_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stats = GeoCallStats()
    stats.observe_dataset(CURRENT)
    stats.observe_dataset(DatasetRef(version_token=VERSION, data_token=OTHER))
    with caplog.at_level(logging.WARNING):
        metadata = geo_run_metadata(GeoApplied(reverse=True, geocode=False), CURRENT, stats)
    assert metadata["geo_dataset_mismatch"] is True
    assert len(_etl_warnings(caplog)) == 1


def test_no_current_token_is_never_mismatch() -> None:
    stats = GeoCallStats()
    stats.observe_dataset(DatasetRef(version_token=VERSION, data_token=OTHER))
    metadata = geo_run_metadata(GeoApplied(reverse=True, geocode=False), None, stats)
    assert metadata["geo_dataset_mismatch"] is False
    assert metadata["geo_data_token"] == "none"


def test_resource_without_base_url_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL", raising=False)
    value = resources.kor_travel_geo_dataset_resource.resource_fn(build_init_resource_context())
    assert value is None


def test_resource_reads_the_current_dataset_once(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

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

    real = httpx.AsyncClient

    def client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setenv("KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL", "http://geo.test")
    monkeypatch.setenv("KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY", "k" * 16)
    monkeypatch.setattr(resources.httpx, "AsyncClient", client_factory)
    value = resources.kor_travel_geo_dataset_resource.resource_fn(build_init_resource_context())
    assert value == CURRENT
    assert seen == ["/v2/dataset/version"]
