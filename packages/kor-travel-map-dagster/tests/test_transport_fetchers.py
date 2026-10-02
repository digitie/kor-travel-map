"""kor-travel-transport export fetcher (ADR-106) — cursor·인증·404/503 해석·계수."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from kortravelmap.providers.kor_travel_transport import (
    SERVICE_TOKEN_HEADER,
    TransportExportContractError,
)
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

import kortravelmap.dagster.provider_fetchers as provider_fetchers
from kortravelmap.dagster.provider_fetchers import (
    ProviderCredentialMissing,
    fetch_transport_airports,
    fetch_transport_fuel_stations,
    fetch_transport_highway_incidents,
    fetch_transport_rest_area_fuel_prices,
    fetch_transport_rest_areas,
)
from kortravelmap.dagster.upstream_requests import (
    counting_upstream_requests,
    observed_upstream_requests,
)

GOLDEN = Path(__file__).resolve().parents[3] / "contracts" / "kor-travel-transport" / "golden"
TOKEN = "t" * 40


def _golden(name: str) -> dict[str, Any]:
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


def _settings(**overrides: Any) -> KorTravelMapSettings:
    values: dict[str, Any] = {
        "kor_travel_transport_base_url": "http://127.0.0.1:14001",
        "kor_travel_transport_service_token": SecretStr(TOKEN),
        "kor_travel_transport_page_size": 1,
    }
    values.update(overrides)
    return KorTravelMapSettings(**values)


def _install(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    real_client = httpx.AsyncClient

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(recording), **kwargs)

    monkeypatch.setattr(provider_fetchers.httpx, "AsyncClient", factory)
    return seen


async def test_fuel_stations_follow_the_cursor_with_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _golden("fuel-stations.json")
    first, second = body["items"]
    pages = {
        None: {**body, "items": [first], "has_more": True, "next_cursor": "7"},
        "7": {**body, "items": [second], "has_more": False, "next_cursor": None},
    }
    seen = _install(
        monkeypatch,
        lambda request: httpx.Response(200, json=pages[request.url.params.get("cursor")]),
    )
    with counting_upstream_requests():
        stations = [station async for station in fetch_transport_fuel_stations(_settings())]
        counted = observed_upstream_requests()
    assert [station.uni_id for station in stations] == [first["natural_key"], second["natural_key"]]
    assert [request.url.path for request in seen] == ["/v1/service/exports/fuel-stations"] * 2
    assert all(request.headers[SERVICE_TOKEN_HEADER] == TOKEN for request in seen)
    assert seen[0].url.params["limit"] == "1"
    assert "cursor" not in seen[0].url.params
    assert counted == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"kor_travel_transport_base_url": None},
        {"kor_travel_transport_base_url": "  "},
        {"kor_travel_transport_service_token": None},
        # compose의 ``${X:-}``는 빈 문자열을 넘긴다 — 미설정과 같게 본다.
        {"kor_travel_transport_service_token": SecretStr("")},
    ],
)
async def test_missing_connection_settings_fail_before_any_request(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any]
) -> None:
    seen = _install(monkeypatch, lambda request: httpx.Response(200, json={}))
    with pytest.raises(ProviderCredentialMissing):
        _ = [item async for item in fetch_transport_rest_areas(_settings(**overrides))]
    assert seen == []


async def test_a_hidden_route_is_reported_as_token_or_host_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, lambda request: httpx.Response(404, json={"detail": "Not Found"}))
    with pytest.raises(ProviderCredentialMissing, match="토큰 불일치"):
        _ = [item async for item in fetch_transport_airports(_settings())]


async def test_a_stale_incident_set_fails_instead_of_ending_every_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """503(수집 실패·정체)을 빈 집합으로 바꾸면 활성 사건이 전부 해소로 오판된다."""
    _install(monkeypatch, lambda request: httpx.Response(503, json={"detail": "stale"}))
    with pytest.raises(httpx.HTTPStatusError):
        _ = [item async for item in fetch_transport_highway_incidents(_settings())]


async def test_an_empty_active_set_is_a_confirmed_fact(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {**_golden("highway-incidents-active.json"), "items": []}
    _install(monkeypatch, lambda request: httpx.Response(200, json=body))
    assert [item async for item in fetch_transport_highway_incidents(_settings())] == []


async def test_a_non_advancing_cursor_is_a_contract_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {**_golden("rest-area-fuel-prices.json"), "has_more": True, "next_cursor": "3"}
    _install(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(TransportExportContractError, match="next_cursor"):
        _ = [item async for item in fetch_transport_rest_area_fuel_prices(_settings())]


async def test_airports_and_rest_areas_parse_the_golden_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = {
        "/v1/service/exports/airports": _golden("airports.json"),
        "/v1/service/exports/rest-areas": _golden("rest-areas.json"),
    }
    _install(monkeypatch, lambda request: httpx.Response(200, json=responses[request.url.path]))
    airports = [item async for item in fetch_transport_airports(_settings())]
    areas = [item async for item in fetch_transport_rest_areas(_settings())]
    assert {airport.code for airport in airports} >= {"ICN", "KPO"}
    assert [area.natural_key for area in areas] == [
        item["natural_key"] for item in _golden("rest-areas.json")["items"]
    ]
