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
    TRANSPORT_BUSY_CODES,
    TRANSPORT_PROBLEM_CODES,
    TRANSPORT_RETRY_LATER_CODES,
    TRANSPORT_SOURCE_NOT_CURRENT_CODES,
    TRANSPORT_T4_ONLY_CODES,
    TRANSPORT_TERMINAL_CODES,
    TransportExportBusy,
    TransportExportContractError,
    TransportExportDisabled,
    TransportExportEmpty,
    TransportExportHidden,
    TransportExportMalformed,
    TransportExportNotCurrent,
    TransportExportTooLarge,
    TransportSourceInconsistent,
    TransportSourceNotCurrent,
)
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

import kortravelmap.dagster.provider_fetchers as provider_fetchers
from kortravelmap.dagster import upstream_retry
from kortravelmap.dagster.provider_fetchers import (
    ProviderCredentialMissing,
    TransportExportUnchanged,
    _TransportTransientStatus,
    fetch_transport_airports,
    fetch_transport_ferry_ports,
    fetch_transport_fuel_stations,
    fetch_transport_highway_incidents,
    fetch_transport_rail_stations,
    fetch_transport_rest_area_fuel_prices,
    fetch_transport_rest_areas,
)
from kortravelmap.dagster.transport_http_metrics import (
    observing_transport_http,
    parse_server_timing,
    transport_http_metadata,
)
from kortravelmap.dagster.upstream_requests import (
    counting_upstream_requests,
    observed_upstream_requests,
)

GOLDEN = (
    Path(__file__).resolve().parents[3] / "tests" / "unit" / "golden" / "kor-travel-transport"
)
TOKEN = "t" * 40


def _golden(name: str) -> dict[str, Any]:
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


def _settings(**overrides: Any) -> KorTravelMapSettings:
    values: dict[str, Any] = {
        "kor_travel_transport_base_url": "http://127.0.0.1:14001",
        "kor_travel_transport_service_token": SecretStr(TOKEN),
        "kor_travel_transport_page_size": 1,
        "kor_travel_transport_reference_page_size": 1,
    }
    values.update(overrides)
    return KorTravelMapSettings(**values)


@pytest.fixture(autouse=True)
def retry_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """HTTP 층 재시도 대기를 기록만 한다. backoff 기준은 0 — 남는 대기는 ``Retry-After``뿐이다."""
    slept: list[float] = []

    async def _record(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(provider_fetchers, "_TRANSPORT_RETRY_BASE_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(provider_fetchers, "_TRANSPORT_BUSY_BASE_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(provider_fetchers, "_transport_retry_sleep", _record)
    return slept


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


async def test_transport_fetchers_in_one_run_share_one_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """한 run 안의 transport fetcher는 재시도 예산 **하나**를 나눠 쓴다.

    큐 run 하나는 scope 여러 개(주유소·휴게소·돌발·공항)를 차례로 돈다. fetcher마다 새 예산을
    만들면 transport가 내려가 있을 때 run 하나가 fetcher 수 × 예산만큼 재시도한다.
    """

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    seen = _install(monkeypatch, broken)
    with upstream_retry.sharing_run_retry_budget(upstream_retry.RetryBudget(limit=1)) as budget:
        with pytest.raises(httpx.ConnectError):
            _ = [item async for item in fetch_transport_airports(_settings())]
        with pytest.raises(httpx.ConnectError):
            _ = [item async for item in fetch_transport_highway_incidents(_settings())]
        with pytest.raises(httpx.ConnectError):
            _ = [item async for item in fetch_transport_rest_areas(_settings())]
    # 첫 fetcher가 예산 1을 다 쓰면(2회) 나머지는 재시도 없이 1회씩 — 종전은 2+2+2.
    assert len(seen) == 4
    assert budget.used == 1


def test_a_nested_run_scope_reuses_the_outer_budget() -> None:
    """큐 run(바깥)이 연 예산을 scope별 runner(안쪽)가 새로 만들지 않는다."""
    with (
        upstream_retry.sharing_run_retry_budget() as outer,
        upstream_retry.sharing_run_retry_budget() as inner,
    ):
        assert inner is outer
        assert upstream_retry.active_run_retry_budget() is outer
    assert upstream_retry.active_run_retry_budget() is None


@pytest.mark.parametrize(
    ("fetch", "body"),
    [
        (fetch_transport_airports, "<html>bad gateway</html>"),
        (fetch_transport_rest_areas, "{not json"),
        (fetch_transport_highway_incidents, ""),
    ],
)
async def test_a_non_json_body_is_malformed_upstream(
    monkeypatch: pytest.MonkeyPatch, fetch: Any, body: str
) -> None:
    """JSON이 아닌 200 본문은 미분류 ``JSONDecodeError``가 아니라 malformed upstream이다."""
    _install(monkeypatch, lambda request: httpx.Response(200, text=body))
    with pytest.raises(TransportExportMalformed) as raised:
        _ = [item async for item in fetch(_settings())]
    assert raised.value.failure_kind == "transport_malformed_upstream"


async def test_an_empty_airport_export_is_a_transport_empty_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, lambda request: httpx.Response(200, json={"items": []}))
    with pytest.raises(TransportExportEmpty) as raised:
        _ = [item async for item in fetch_transport_airports(_settings())]
    assert raised.value.failure_kind == "transport_empty"


async def test_a_503_is_not_retried_at_the_http_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """503은 HTTP 층에서 곧바로 다시 부르지 않는다(15초 안에 바뀌지 않는다).

    step 재시도가 남는지는 ``test_quota_exhaustion_stops_step_retries.py``의 transport
    경계 테스트가 실제 asset 경계로 확인한다.
    """
    seen = _install(monkeypatch, lambda request: httpx.Response(503, json={"detail": "stale"}))
    with pytest.raises(TransportExportNotCurrent):
        _ = [item async for item in fetch_transport_airports(_settings())]
    assert len(seen) == 1


def test_an_explicit_budget_under_an_open_run_scope_is_refused() -> None:
    """바깥 run 예산이 열려 있으면 안쪽이 넘긴 예산은 쓰이지 않는다 — 조용히 무시하지 않는다."""
    with (
        upstream_retry.sharing_run_retry_budget(),
        pytest.raises(ValueError, match="예산"),
        upstream_retry.sharing_run_retry_budget(upstream_retry.RetryBudget(limit=1)),
    ):
        pass


# -- 기준정보 snapshot export(철도역·항구, ADR-120) ---------------------------------


def _reference_pages(name: str) -> dict[str | None, dict[str, Any]]:
    """golden 한 장을 한 행씩 cursor 페이지로 나눈다(같은 snapshot_id·total_count)."""
    body = _golden(name)
    items = body["items"]
    pages: dict[str | None, dict[str, Any]] = {}
    cursor: str | None = None
    for index, item in enumerate(items):
        following = f"c{index + 1}" if index + 1 < len(items) else None
        pages[cursor] = {
            **body,
            "meta": {**body["meta"], "item_count": 1},
            "items": [item],
            "has_more": following is not None,
            "next_cursor": following,
        }
        cursor = following
    return pages


@pytest.mark.parametrize(
    ("fetch", "name", "path"),
    [
        (fetch_transport_rail_stations, "rail-stations.json", "/v1/service/exports/rail-stations"),
        (fetch_transport_ferry_ports, "ferry-ports.json", "/v1/service/exports/ferry-ports"),
    ],
)
async def test_reference_exports_read_one_snapshot_to_the_end(
    monkeypatch: pytest.MonkeyPatch, fetch: Any, name: str, path: str
) -> None:
    pages = _reference_pages(name)
    seen = _install(
        monkeypatch,
        lambda request: httpx.Response(200, json=pages[request.url.params.get("cursor")]),
    )
    with counting_upstream_requests():
        items = [item async for item in fetch(_settings())]
        counted = observed_upstream_requests()
    assert [item.natural_key for item in items] == [
        item["natural_key"] for item in _golden(name)["items"]
    ]
    assert [request.url.path for request in seen] == [path] * len(items)
    assert all(request.headers[SERVICE_TOKEN_HEADER] == TOKEN for request in seen)
    # transport는 cursor에 limit을 결박한다 — 모든 페이지에 같은 limit.
    assert {request.url.params["limit"] for request in seen} == {"1"}
    assert counted == len(items)


async def test_a_reference_snapshot_that_changes_mid_walk_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = _reference_pages("rail-stations.json")
    pages["c1"] = {**pages["c1"], "snapshot_id": "00000000-0000-4000-8000-000000000000"}
    _install(
        monkeypatch,
        lambda request: httpx.Response(200, json=pages[request.url.params.get("cursor")]),
    )
    with pytest.raises(TransportExportContractError, match="snapshot"):
        _ = [item async for item in fetch_transport_rail_stations(_settings())]


async def test_a_reference_snapshot_short_of_its_total_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _golden("ferry-ports.json")
    short = {**body, "total_count": 4}
    _install(monkeypatch, lambda request: httpx.Response(200, json=short))
    with pytest.raises(TransportExportContractError, match="total_count"):
        _ = [item async for item in fetch_transport_ferry_ports(_settings())]


@pytest.mark.parametrize("status", [503, 410])
async def test_a_disabled_or_expired_reference_export_loads_nothing(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """503(export 꺼짐·완결 성공 없음)과 410(snapshot 만료)은 적재 없이 retryable 실패다."""
    detail = {"detail": "터미널 export가 활성화되지 않았습니다."}
    seen = _install(monkeypatch, lambda request: httpx.Response(status, json=detail))
    with pytest.raises(TransportExportNotCurrent) as raised:
        _ = [item async for item in fetch_transport_rail_stations(_settings())]
    assert raised.value.retryable is True
    # 410은 새 snapshot으로 한 번 다시 읽는다(첫 페이지부터), 503은 바로 실패한다.
    assert len(seen) == (2 if status == 410 else 1)


async def test_a_snapshot_expiring_mid_walk_is_reread_from_the_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """transport는 410을 cursor 페이지에서만 낸다 — 첫 페이지부터 새 snapshot으로 한 번 다시 읽고
    옛 snapshot의 앞 페이지와 섞지 않는다. 두 번째도 만료면 retryable 실패다."""
    pages = _reference_pages("rail-stations.json")
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        calls.append(cursor)
        if cursor == "c1" and calls.count("c1") == 1:
            return httpx.Response(410, json={"detail": "snapshot이 만료되었습니다."})
        return httpx.Response(200, json=pages[cursor])

    _install(monkeypatch, handler)
    stations = [item async for item in fetch_transport_rail_stations(_settings())]
    assert [s.natural_key for s in stations] == [
        item["natural_key"] for item in _golden("rail-stations.json")["items"]
    ]
    assert calls == [None, "c1", None, "c1", "c2"]

    def always_expired(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") is None:
            return httpx.Response(200, json=pages[None])
        return httpx.Response(410, json={"detail": "snapshot이 만료되었습니다."})

    _install(monkeypatch, always_expired)
    with pytest.raises(TransportExportNotCurrent) as raised:
        _ = [item async for item in fetch_transport_rail_stations(_settings())]
    assert raised.value.failure_kind == "transport_snapshot_expired"
    assert raised.value.retryable is True


async def test_a_total_count_drifting_mid_walk_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = _reference_pages("ferry-ports.json")
    pages["c1"] = {**pages["c1"], "total_count": 4}
    _install(
        monkeypatch,
        lambda request: httpx.Response(200, json=pages[request.url.params.get("cursor")]),
    )
    with pytest.raises(TransportExportContractError, match="snapshot"):
        _ = [item async for item in fetch_transport_ferry_ports(_settings())]


async def test_a_cycling_reference_cursor_is_a_contract_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _golden("rail-stations.json")
    following = {None: "A", "A": "B", "B": "A"}

    def handler(request: httpx.Request) -> httpx.Response:
        page = {
            **body,
            "meta": {**body["meta"], "item_count": 1},
            "items": body["items"][:1],
            "has_more": True,
            "next_cursor": following[request.url.params.get("cursor")],
        }
        return httpx.Response(200, json=page)

    _install(monkeypatch, handler)
    with pytest.raises(TransportExportContractError, match="순환"):
        _ = [item async for item in fetch_transport_rail_stations(_settings())]


async def test_an_empty_reference_snapshot_is_a_transport_empty_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _golden("rail-stations.json")
    empty = {**body, "meta": {**body["meta"], "item_count": 0}, "items": [], "total_count": 0}
    _install(monkeypatch, lambda request: httpx.Response(200, json=empty))
    with pytest.raises(TransportExportEmpty):
        _ = [item async for item in fetch_transport_rail_stations(_settings())]


async def test_a_stale_reference_snapshot_is_loaded_as_the_last_complete_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _golden("ferry-ports.json")
    stale = {**body, "meta": {**body["meta"], "source_status": "stale"}}
    _install(monkeypatch, lambda request: httpx.Response(200, json=stale))
    ports = [item async for item in fetch_transport_ferry_ports(_settings())]
    assert len(ports) == len(body["items"])


# ---------------------------------------------- 503 problem code·HTTP 층 재시도(2026-11-24 계약)


def _problem(status: int, code: str | None, *, retry_after: str | None = None) -> httpx.Response:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": "Service Unavailable",
        "status": status,
        "detail": "근거 수집이 현재가 아니다",
        "instance": "/v1/service/exports/x",
    }
    if code is not None:
        body["code"] = code
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return httpx.Response(
        status, json=body, headers={"content-type": "application/problem+json", **headers}
    )


@pytest.mark.parametrize(
    ("code", "retry_after", "kind", "fetch"),
    [
        (
            "EXPORT_SOURCE_NOT_CURRENT",
            "1800",
            "transport_source_not_current",
            fetch_transport_fuel_stations,
        ),
        (
            "EXPORT_NO_HISTORY",
            "3600",
            "transport_no_history",
            fetch_transport_rest_area_fuel_prices,
        ),
        (
            "EXPORT_INCIDENTS_NOT_CURRENT",
            "300",
            "transport_incidents_not_current",
            fetch_transport_highway_incidents,
        ),
        ("EXPORT_EMPTY_SET", "300", "transport_empty_set", fetch_transport_highway_incidents),
    ],
)
async def test_a_coded_not_current_503_is_not_retried_and_not_retryable(
    monkeypatch: pytest.MonkeyPatch,
    retry_sleeps: list[float],
    code: str,
    retry_after: str,
    kind: str,
    fetch: Any,
) -> None:
    """다음 정기 수집 전에는 풀리지 않는 503 — HTTP 층도 step도 다시 부르지 않는다(run은 실패).

    ``Retry-After``는 힌트로 실릴 뿐 대기에 쓰이지 않는다 — 값과 무관하게 같은 분류다.
    """
    seen = _install(monkeypatch, lambda request: _problem(503, code, retry_after=retry_after))
    with pytest.raises(TransportSourceNotCurrent) as raised:
        _ = [item async for item in fetch(_settings())]
    # 예외는 retryable — step 재시도 여부는 job 경계가 정한다
    # (feature 적재는 재시도, 상태 job은 나이 기준 혼합).
    assert raised.value.retryable is True
    assert raised.value.code == code
    assert raised.value.retry_after == float(retry_after)
    assert raised.value.failure_kind == kind
    assert len(seen) == 1
    assert retry_sleeps == []


async def test_a_busy_503_retries_the_same_page_honouring_retry_after(
    monkeypatch: pytest.MonkeyPatch, retry_sleeps: list[float]
) -> None:
    body = _golden("fuel-stations.json")
    first, second = body["items"]
    pages = {
        None: {**body, "items": [first], "has_more": True, "next_cursor": "7"},
        "7": {**body, "items": [second], "has_more": False, "next_cursor": None},
    }
    busy_once = iter([_problem(503, "EXPORT_BUSY", retry_after="10")])

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        if cursor == "7":
            busy = next(busy_once, None)
            if busy is not None:
                return busy
        return httpx.Response(200, json=pages[cursor])

    seen = _install(monkeypatch, handler)
    with counting_upstream_requests(), observing_transport_http() as metrics:
        stations = [station async for station in fetch_transport_fuel_stations(_settings())]
        counted = observed_upstream_requests()
    assert [station.uni_id for station in stations] == [first["natural_key"], second["natural_key"]]
    # 같은 cursor만 다시 묻는다 — 첫 페이지부터 다시 읽지 않는다.
    assert [request.url.params.get("cursor") for request in seen] == [None, "7", "7"]
    assert retry_sleeps == [10.0]
    assert counted == 3
    assert metrics.retries == 1
    assert metrics.statuses == {"200": 2, "503": 1}


async def test_a_busy_503_gives_up_after_the_attempt_cap_and_stays_retryable(
    monkeypatch: pytest.MonkeyPatch, retry_sleeps: list[float]
) -> None:
    seen = _install(monkeypatch, lambda request: _problem(503, "TRANSIENT_DB", retry_after="15"))
    with pytest.raises(TransportExportBusy) as raised:
        _ = [item async for item in fetch_transport_airports(_settings())]
    assert raised.value.retryable is True  # step 재시도(첫 페이지부터)는 남는다
    assert raised.value.failure_kind == "transport_transient_db"
    assert len(seen) == 4
    assert retry_sleeps == [15.0, 15.0, 15.0]


async def test_a_busy_503_with_a_long_retry_after_is_not_waited_and_not_retryable(
    monkeypatch: pytest.MonkeyPatch, retry_sleeps: list[float]
) -> None:
    seen = _install(
        monkeypatch, lambda request: _problem(503, "EXPORT_PREPARE_TIMEOUT", retry_after="120")
    )
    with pytest.raises(TransportExportBusy) as raised:
        _ = [item async for item in fetch_transport_rail_stations(_settings())]
    assert raised.value.retryable is True
    assert raised.value.retry_after_exceeds_cap is True
    assert raised.value.failure_kind == "transport_prepare_timeout"
    assert len(seen) == 1
    assert retry_sleeps == []


async def test_busy_retries_spend_the_shared_run_retry_budget(
    monkeypatch: pytest.MonkeyPatch, retry_sleeps: list[float]
) -> None:
    seen = _install(monkeypatch, lambda request: _problem(503, "EXPORT_BUSY", retry_after="10"))
    with (
        upstream_retry.sharing_run_retry_budget(upstream_retry.RetryBudget(limit=1)) as budget,
        pytest.raises(TransportExportBusy),
    ):
        _ = [item async for item in fetch_transport_airports(_settings())]
    assert len(seen) == 2
    assert budget.used == 1


@pytest.mark.parametrize(
    "response",
    [
        _problem(503, "SERVICE_UNAVAILABLE", retry_after="30"),  # 앞으로 붙을 공통 code
        _problem(503, "export_busy"),  # UPPER_SNAKE가 아니다
        _problem(503, None),
        httpx.Response(503, text="<html>bad gateway</html>"),
    ],
    ids=["unknown-code", "malformed-code", "no-code", "not-json"],
)
async def test_an_unknown_or_missing_code_keeps_the_old_503_behaviour(
    monkeypatch: pytest.MonkeyPatch, retry_sleeps: list[float], response: httpx.Response
) -> None:
    seen = _install(monkeypatch, lambda request: response)
    with pytest.raises(TransportExportNotCurrent) as raised:
        _ = [item async for item in fetch_transport_fuel_stations(_settings())]
    assert type(raised.value) is TransportExportNotCurrent
    assert raised.value.retryable is True
    assert raised.value.failure_kind == "transport_not_current"
    assert len(seen) == 1
    assert retry_sleeps == []


@pytest.mark.parametrize(
    ("status", "retry_after", "expected_sleep"),
    [(500, None, 0.0), (408, None, 0.0), (429, "7", 7.0)],
)
async def test_500_408_429_are_retried_at_the_http_layer(
    monkeypatch: pytest.MonkeyPatch,
    retry_sleeps: list[float],
    status: int,
    retry_after: str | None,
    expected_sleep: float,
) -> None:
    body = _golden("airports.json")
    responses = iter(
        [_problem(status, None, retry_after=retry_after), httpx.Response(200, json=body)]
    )
    seen = _install(monkeypatch, lambda request: next(responses))
    airports = [item async for item in fetch_transport_airports(_settings())]
    assert airports
    assert len(seen) == 2
    assert retry_sleeps == [expected_sleep]


async def test_a_429_with_a_long_retry_after_is_left_to_step_retries(
    monkeypatch: pytest.MonkeyPatch, retry_sleeps: list[float]
) -> None:
    seen = _install(monkeypatch, lambda request: _problem(429, None, retry_after="300"))
    with pytest.raises(_TransportTransientStatus) as raised:
        _ = [item async for item in fetch_transport_airports(_settings())]
    assert raised.value.retryable is True
    assert raised.value.retry_after == 300.0
    assert len(seen) == 1
    assert retry_sleeps == []


@pytest.mark.parametrize("status", [400, 422])
async def test_a_rejected_request_is_a_contract_error_and_not_retried(
    monkeypatch: pytest.MonkeyPatch, retry_sleeps: list[float], status: int
) -> None:
    seen = _install(monkeypatch, lambda request: _problem(status, "INVALID_CURSOR"))
    with pytest.raises(TransportExportContractError) as raised:
        _ = [item async for item in fetch_transport_fuel_stations(_settings())]
    assert raised.value.retryable is False
    assert raised.value.failure_kind == "transport_request_rejected"
    assert len(seen) == 1


# ---------------------------------------------- 바뀌지 않은 집합 건너뛰기(감사 MC-04)


def _two_fuel_pages(second_success_at: str | None = None) -> dict[str | None, Any]:
    body = _golden("fuel-stations.json")
    first, second = body["items"]
    second_collection = dict(body["collection"])
    if second_success_at is not None:
        second_collection["last_success_at"] = second_success_at
    return {
        None: {**body, "items": [first], "has_more": True, "next_cursor": "7"},
        "7": {
            **body,
            "items": [second],
            "has_more": False,
            "next_cursor": None,
            "collection": second_collection,
        },
    }


_GOLDEN_FUEL_SUCCESS = datetime.fromisoformat("2026-10-02T07:34:44+00:00")


async def test_an_unchanged_first_page_stops_the_walk(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = _two_fuel_pages()
    seen = _install(
        monkeypatch,
        lambda request: httpx.Response(200, json=pages[request.url.params.get("cursor")]),
    )
    with pytest.raises(TransportExportUnchanged) as raised:
        _ = [
            item
            async for item in fetch_transport_fuel_stations(
                _settings(), unchanged_since=_GOLDEN_FUEL_SUCCESS
            )
        ]
    assert raised.value.last_success_at == _GOLDEN_FUEL_SUCCESS
    assert len(seen) == 1


async def test_a_changed_first_page_walks_to_the_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """판단은 첫 페이지 하나로만 한다 — 뒤 페이지가 기준과 같아도 멈추지 않는다."""
    pages = _two_fuel_pages(second_success_at="2026-10-01T23:00:00Z")
    pages[None] = {
        **pages[None],
        "collection": {**pages[None]["collection"], "last_success_at": "2026-10-02T15:34:44Z"},
    }
    seen = _install(
        monkeypatch,
        lambda request: httpx.Response(200, json=pages[request.url.params.get("cursor")]),
    )
    stations = [
        item
        async for item in fetch_transport_fuel_stations(
            _settings(), unchanged_since=datetime.fromisoformat("2026-10-01T23:00:00+00:00")
        )
    ]
    assert len(stations) == 2
    assert len(seen) == 2


# ---------------------------------------------- 요청 계측(감사 G2-07)


async def test_requests_are_timed_with_the_transport_server_timing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = _two_fuel_pages()
    timings = {
        None: 'app;dur=12.4, sql;dur=3.25, sql_count;desc="4", cpu;dur=1.0',
        "7": 'app;dur=20.6, sql;dur=1.5, page_builds;desc="0"',
    }

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        return httpx.Response(200, json=pages[cursor], headers={"Server-Timing": timings[cursor]})

    _install(monkeypatch, handler)
    with observing_transport_http():
        _ = [item async for item in fetch_transport_fuel_stations(_settings())]
        metadata = transport_http_metadata()
    assert metadata["transport_http_requests"] == 2
    assert metadata["transport_http_statuses"] == "200=2"
    assert metadata["transport_server_timed"] == 2
    assert metadata["transport_server_app_ms_total"] == 33
    assert metadata["transport_server_app_ms_max"] == 21
    assert metadata["transport_server_sql_ms_total"] == 5
    assert metadata["transport_http_retries"] == 0
    assert int(metadata["transport_http_ms_total"]) >= int(metadata["transport_http_first_ms"])


async def test_requests_are_not_reported_outside_a_measuring_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = _two_fuel_pages()
    _install(
        monkeypatch,
        lambda request: httpx.Response(200, json=pages[request.url.params.get("cursor")]),
    )
    _ = [item async for item in fetch_transport_fuel_stations(_settings())]
    assert transport_http_metadata() == {}


async def test_reference_exports_use_their_own_page_size(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _golden("rail-stations.json")
    seen = _install(monkeypatch, lambda request: httpx.Response(200, json=body))
    settings = _settings(kor_travel_transport_reference_page_size=len(body["items"]))
    _ = [item async for item in fetch_transport_rail_stations(settings)]
    assert seen[0].url.params["limit"] == str(len(body["items"]))


def test_server_timing_parsing_keeps_only_durations() -> None:
    assert parse_server_timing(None) == {}
    assert parse_server_timing('app;dur=1.5, sql;dur="2", sql_count;desc="3"') == {
        "app": 1.5,
        "sql": 2.0,
    }
    # 읽을 수 없는 값·음수·무한대는 건너뛰고, 같은 이름이 거듭되면 처음 것.
    assert parse_server_timing("app;dur=x, sql;dur=-1, cpu;dur=inf, app;dur=9, db;dur=4") == {
        "app": 9.0,
        "db": 4.0,
    }


# ---------------------------------------------- 나머지 producer code·대기 상한(2026-11-24 리뷰)


def test_every_producer_code_is_classified_exactly_once() -> None:
    """transport ``ProblemCode`` 11종(PR #277 ``backend/app/core/problems.py``).

    T1~T3 열 개는 넷으로 나뉘고 겹치지 않는다. ``EXPORT_QUERY_TIMEOUT``은 T4(가격 이력) 전용이라
    fetcher 분류에서 뺀다
    (fetcher에 오면 모르는 code — retryable 일시 오류). transport ``docs/openapi.json``은 code를
    enum으로 내지 않아 거기서 유도하지 못한다 — transport가 code를 더하면 이 목록을 함께 고친다."""
    t4_only = {"EXPORT_QUERY_TIMEOUT"}
    assert t4_only == set(TRANSPORT_T4_ONLY_CODES)
    assert not t4_only & set(TRANSPORT_PROBLEM_CODES)
    producer = {
        "EXPORT_SOURCE_NOT_CURRENT",
        "EXPORT_NO_HISTORY",
        "EXPORT_INCIDENTS_NOT_CURRENT",
        "EXPORT_EMPTY_SET",
        "EXPORT_BUSY",
        "EXPORT_PREPARE_TIMEOUT",
        "EXPORT_DISABLED",
        "EXPORT_SOURCE_INCONSISTENT",
        "EXPORT_TOO_LARGE",
        "TRANSIENT_DB",
    }
    groups = [
        TRANSPORT_SOURCE_NOT_CURRENT_CODES,
        TRANSPORT_BUSY_CODES,
        TRANSPORT_TERMINAL_CODES,
        TRANSPORT_RETRY_LATER_CODES,
    ]
    assert set(TRANSPORT_PROBLEM_CODES) == producer
    assert sum(len(group) for group in groups) == len(producer)


@pytest.mark.parametrize(
    ("code", "expected", "kind"),
    [
        ("EXPORT_DISABLED", TransportExportDisabled, "transport_export_disabled"),
        ("EXPORT_TOO_LARGE", TransportExportTooLarge, "transport_export_too_large"),
    ],
)
async def test_a_disabled_or_too_large_export_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
    retry_sleeps: list[float],
    code: str,
    expected: type[Exception],
    kind: str,
) -> None:
    """설정·데이터가 바뀌기 전에는 결정적으로 같다 — HTTP 층도 step도 다시 부르지 않는다."""
    seen = _install(monkeypatch, lambda request: _problem(503, code, retry_after="3600"))
    with pytest.raises(expected) as raised:
        _ = [item async for item in fetch_transport_rail_stations(_settings())]
    assert raised.value.retryable is False  # type: ignore[attr-defined]
    assert raised.value.failure_kind == kind  # type: ignore[attr-defined]
    assert raised.value.code == code  # type: ignore[attr-defined]
    assert raised.value.retry_after == 3600.0  # type: ignore[attr-defined]
    assert len(seen) == 1
    assert retry_sleeps == []


async def test_an_inconsistent_source_is_left_to_step_retries(
    monkeypatch: pytest.MonkeyPatch, retry_sleeps: list[float]
) -> None:
    """transport의 다음 수집·준비가 고친다 — HTTP 층에서는 같은 근거를 다시 묻지 않는다."""
    seen = _install(
        monkeypatch,
        lambda request: _problem(503, "EXPORT_SOURCE_INCONSISTENT", retry_after="300"),
    )
    with pytest.raises(TransportSourceInconsistent) as raised:
        _ = [item async for item in fetch_transport_fuel_stations(_settings())]
    assert raised.value.retryable is True
    assert raised.value.failure_kind == "transport_source_inconsistent"
    assert raised.value.retry_after == 300.0
    assert len(seen) == 1
    assert retry_sleeps == []


async def test_a_prepare_timeout_at_the_wait_cap_is_still_waited(
    monkeypatch: pytest.MonkeyPatch, retry_sleeps: list[float]
) -> None:
    """transport 기본 ``EXPORT_PREPARE_TIMEOUT`` Retry-After(60초)는 상한과 같다.

    같으면 기다린다.
    """
    body = _golden("airports.json")
    responses = iter(
        [
            _problem(503, "EXPORT_PREPARE_TIMEOUT", retry_after="60"),
            httpx.Response(200, json=body),
        ]
    )
    seen = _install(monkeypatch, lambda request: next(responses))
    airports = [item async for item in fetch_transport_airports(_settings())]
    assert airports
    assert len(seen) == 2
    assert retry_sleeps == [60.0]


async def test_a_prepare_timeout_above_the_wait_cap_becomes_terminal(
    monkeypatch: pytest.MonkeyPatch,
    retry_sleeps: list[float],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """transport가 그 값을 60초 위로 올리면 기다리지 않고 재시도 없는 실패다.

    조용히 바뀌지 않게 예외 문장과 경고 log에 남긴다.
    """
    seen = _install(
        monkeypatch, lambda request: _problem(503, "EXPORT_PREPARE_TIMEOUT", retry_after="61")
    )
    with caplog.at_level("WARNING"), pytest.raises(TransportExportBusy) as raised:
        _ = [item async for item in fetch_transport_airports(_settings())]
    assert raised.value.retryable is True  # 기다리지 않을 뿐 — step 재시도 여부는 job 경계
    assert raised.value.retry_after_exceeds_cap is True
    assert "대기 상한" in str(raised.value)
    assert any("대기 상한" in record.getMessage() for record in caplog.records)
    assert len(seen) == 1
    assert retry_sleeps == []


async def test_busy_waits_are_jittered_but_never_below_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """경합 backoff(5·10·20초)는 ±20% 흔들리고, ``Retry-After``는 하한으로 그대로다."""
    monkeypatch.setattr(provider_fetchers, "_TRANSPORT_BUSY_BASE_DELAY_SECONDS", 5.0)
    monkeypatch.setattr(provider_fetchers, "_transport_busy_jitter", provider_fetchers._jitter)
    busy = TransportExportBusy("503", code="EXPORT_BUSY", retry_after=None, retry_after_cap=60.0)
    for attempt, base in ((1, 5.0), (2, 10.0), (3, 20.0)):
        for _ in range(50):
            delay = provider_fetchers._transport_retry_delay(busy, attempt)
            assert delay is not None
            assert base * 0.8 <= delay <= base * 1.2
    hinted = TransportExportBusy("503", code="EXPORT_BUSY", retry_after=30.0, retry_after_cap=60.0)
    assert provider_fetchers._transport_retry_delay(hinted, 1) == 30.0


async def test_a_wait_that_would_overrun_the_run_retry_time_is_not_taken(
    monkeypatch: pytest.MonkeyPatch, retry_sleeps: list[float]
) -> None:
    """예산의 시간 상한을 넘길 대기는 하지 않는다 — 상태 job이 run 상한을 넘기지 않게."""
    seen = _install(monkeypatch, lambda request: _problem(503, "EXPORT_BUSY", retry_after="40"))
    with (
        upstream_retry.sharing_run_retry_budget(upstream_retry.RetryBudget(max_seconds=60.0)),
        pytest.raises(TransportExportBusy),
    ):
        _ = [item async for item in fetch_transport_airports(_settings())]
    assert retry_sleeps == [40.0]  # 두 번째 40초는 상한 60초를 넘긴다
    assert len(seen) == 2


async def test_linked_rest_areas_carry_the_krex_code_and_the_state_job_summarizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-127: 휴게소 + 먹거리 export → PG용 ``ex_*`` 연결, Valkey용 메뉴 요약."""
    from kortravelmap.dto.transport_state import RestAreaFoodState

    from kortravelmap.dagster.provider_fetchers import fetch_transport_rest_areas_linked
    from kortravelmap.dagster.transport_state import TRANSPORT_STATE_SPECS

    food = _golden("rest-area-food.json")
    responses = {
        "/v1/service/exports/rest-areas": {
            **_golden("rest-areas.json"), "has_more": False, "next_cursor": None,
        },
        "/v1/service/exports/rest-area-food": {**food, "has_more": False, "next_cursor": None},
        "/v1/service/exports/fuel-stations": {
            **_golden("fuel-stations.json"), "has_more": False, "next_cursor": None,
        },
    }
    _install(monkeypatch, lambda request: httpx.Response(200, json=responses[request.url.path]))
    [area] = [item async for item in fetch_transport_rest_areas_linked(_settings())]
    assert area.ex_std_rest_code == "000341"
    assert (area.ex_route_name, area.ex_direction_code) == ("서해안선", "up")

    spec = next(spec for spec in TRANSPORT_STATE_SPECS if spec.job_name.endswith("rest_area_food"))
    collected: list[datetime] = []
    [item] = await spec.collect(_settings(), collected.append)
    state = RestAreaFoodState.model_validate_json(item.value)
    assert state.std_rest_code == "000341"
    assert state.menu_count == 4
    assert state.featured[0].tags == ["best"]
    assert state.source_collected_at == datetime.fromisoformat(
        food["collection"]["last_success_at"].replace("Z", "+00:00")
    )
    assert collected == [state.source_collected_at]


async def test_linked_rest_areas_fail_when_the_food_export_is_not_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.dagster.provider_fetchers import fetch_transport_rest_areas_linked

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("rest-area-food"):
            return httpx.Response(404)
        return httpx.Response(200, json={**_golden("rest-areas.json"), "has_more": False})

    _install(monkeypatch, handler)
    with pytest.raises(TransportExportHidden):
        _ = [item async for item in fetch_transport_rest_areas_linked(_settings())]


async def test_rest_area_food_pages_must_share_one_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.dagster.provider_fetchers import fetch_transport_rest_area_food

    food = _golden("rest-area-food.json")
    first = {**food, "items": food["items"][:1], "has_more": True, "next_cursor": "1"}
    later = {
        **food,
        "items": food["items"][1:],
        "collection": {**food["collection"], "last_success_at": "2026-11-28T18:50:00Z"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=later if request.url.params.get("cursor") else first)

    _install(monkeypatch, handler)
    with pytest.raises(TransportExportNotCurrent, match="세대"):
        _ = [item async for item in fetch_transport_rest_area_food(_settings())]

