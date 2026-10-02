"""kor-travel-transport export fetcher (ADR-106) — cursor·인증·404/503 해석·계수."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from kortravelmap.providers.kor_travel_transport import (
    SERVICE_TOKEN_HEADER,
    TransportExportContractError,
    TransportExportEmpty,
    TransportExportHidden,
    TransportExportNotCurrent,
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

GOLDEN = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "kor-travel-transport"
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


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_fetchers, "_TRANSPORT_RETRY_BASE_DELAY_SECONDS", 0.0)


def _golden_incident_now(monkeypatch: pytest.MonkeyPatch, *, after: timedelta) -> None:
    collected = datetime.fromisoformat(
        _golden("highway-incidents-active.json")["collected_at"].replace("Z", "+00:00")
    )
    monkeypatch.setattr(provider_fetchers, "_utcnow", lambda: collected + after)


#: 진짜 client. 한 테스트가 ``_install``을 여러 번 불러도 패치된 factory를 겹쳐 감싸지 않는다.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _install(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    real_client = _REAL_ASYNC_CLIENT

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


async def test_a_hidden_route_is_not_reported_as_a_missing_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """404는 토큰·접속 주소·버전 셋 중 하나다 — 설정 누락과 가른다(M6).

    설정 누락은 요청 전에 ``ProviderCredentialMissing``으로 난다.
    """
    seen = _install(
        monkeypatch, lambda request: httpx.Response(404, json={"detail": "Not Found"})
    )
    with pytest.raises(TransportExportHidden, match="SERVICE_EXPORT_ALLOWED_CLIENTS_CSV") as raised:
        _ = [item async for item in fetch_transport_airports(_settings())]
    assert not isinstance(raised.value, ProviderCredentialMissing)
    assert raised.value.failure_kind == "transport_hidden"
    assert len(seen) == 1  # 재시도하지 않는다.


async def test_a_stale_incident_set_fails_instead_of_ending_every_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """503(수집 실패·정체)을 빈 집합으로 바꾸면 활성 사건이 전부 해소로 오판된다."""
    seen = _install(monkeypatch, lambda request: httpx.Response(503, json={"detail": "stale"}))
    with pytest.raises(TransportExportNotCurrent) as raised:
        _ = [item async for item in fetch_transport_highway_incidents(_settings())]
    assert raised.value.failure_kind == "transport_not_current"
    assert len(seen) == 1


async def test_an_old_incident_set_fails_even_when_transport_says_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M2: transport의 503에만 기대지 않는다 — collected_at이 30분을 넘으면 Map이 거부한다."""
    _golden_incident_now(monkeypatch, after=timedelta(minutes=31))
    body = _golden("highway-incidents-active.json")
    _install(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(TransportExportNotCurrent, match="지났다"):
        _ = [item async for item in fetch_transport_highway_incidents(_settings())]


async def test_an_empty_active_set_is_a_confirmed_fact(monkeypatch: pytest.MonkeyPatch) -> None:
    _golden_incident_now(monkeypatch, after=timedelta(minutes=5))
    body = {**_golden("highway-incidents-active.json"), "items": []}
    _install(monkeypatch, lambda request: httpx.Response(200, json=body))
    assert [item async for item in fetch_transport_highway_incidents(_settings())] == []


@pytest.mark.parametrize(
    "fetch",
    [
        fetch_transport_fuel_stations,
        fetch_transport_rest_areas,
        fetch_transport_rest_area_fuel_prices,
    ],
)
async def test_a_snapshot_export_refuses_503_flags_and_zero_records(
    monkeypatch: pytest.MonkeyPatch, fetch: Any
) -> None:
    """M1: 완전 snapshot reconcile 근거가 낡거나 비면 적재 전에 실패한다(아무것도 지우지 않는다)."""
    body = {**_golden("rest-areas.json"), "has_more": False, "next_cursor": None}
    _install(monkeypatch, lambda request: httpx.Response(503, json={"detail": "stale"}))
    with pytest.raises(TransportExportNotCurrent):
        _ = [item async for item in fetch(_settings())]

    stale = {**body, "collection": {**body["collection"], "stale": True}}
    _install(monkeypatch, lambda request: httpx.Response(200, json=stale))
    with pytest.raises(TransportExportNotCurrent):
        _ = [item async for item in fetch(_settings())]

    empty = {**body, "items": []}
    _install(monkeypatch, lambda request: httpx.Response(200, json=empty))
    with pytest.raises(TransportExportEmpty) as raised:
        _ = [item async for item in fetch(_settings())]
    assert raised.value.failure_kind == "transport_empty"


async def test_a_late_page_failure_still_fails_the_whole_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """앞 페이지가 성공해도 뒤 페이지가 503이면 전체가 실패한다.

    부분 집합으로 reconcile하지 않는다.
    """
    body = _golden("rest-areas.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") is None:
            return httpx.Response(200, json={**body, "has_more": True, "next_cursor": "9"})
        return httpx.Response(503, json={"detail": "collection failed"})

    _install(monkeypatch, handler)
    with pytest.raises(TransportExportNotCurrent):
        _ = [item async for item in fetch_transport_rest_areas(_settings())]


async def test_transient_errors_are_retried_and_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    """M8: 전송 오류·502/504는 유한 재시도한다. 시도마다 요청 1건으로 센다."""
    body = _golden("airports.json")
    responses = iter([httpx.Response(502), httpx.Response(200, json=body)])
    seen = _install(monkeypatch, lambda request: next(responses))
    with counting_upstream_requests():
        airports = [item async for item in fetch_transport_airports(_settings())]
        counted = observed_upstream_requests()
    assert airports
    assert len(seen) == 2
    assert counted == 2

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    seen = _install(monkeypatch, broken)
    with pytest.raises(httpx.ConnectError):
        _ = [item async for item in fetch_transport_airports(_settings())]
    assert len(seen) == 2  # 시도 상한(2)에서 멈춘다.


async def test_a_cycling_cursor_is_a_contract_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    """M8: 바로 앞 cursor 반복만이 아니라 순환(A→B→A)도 잡는다."""
    body = _golden("rest-area-fuel-prices.json")
    following = {None: "A", "A": "B", "B": "A"}

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        page = {**body, "has_more": True, "next_cursor": following[cursor]}
        return httpx.Response(200, json=page)

    _install(monkeypatch, handler)
    with pytest.raises(TransportExportContractError, match="순환"):
        _ = [item async for item in fetch_transport_rest_area_fuel_prices(_settings())]


async def test_the_page_loop_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """M8: 매번 새 cursor를 주는 고장도 페이지 상한에서 멈춘다."""
    monkeypatch.setattr(provider_fetchers, "_TRANSPORT_MAX_PAGES", 3)
    body = _golden("rest-area-fuel-prices.json")
    counter = iter(range(1, 100))

    def handler(request: httpx.Request) -> httpx.Response:
        page = {**body, "has_more": True, "next_cursor": str(next(counter))}
        return httpx.Response(200, json=page)

    seen = _install(monkeypatch, handler)
    with pytest.raises(TransportExportContractError, match="페이지"):
        _ = [item async for item in fetch_transport_rest_area_fuel_prices(_settings())]
    assert len(seen) == 3


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
