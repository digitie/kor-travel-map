"""다건 호출 provider의 호출 단위 재시도와 쿼터 분류 (감사 2026-11-23 §4 #15, §1.3 P0·P1).

- 일시 오류(5xx·timeout·연결)는 **그 호출 하나만** 다시 부른다 — asset 전체를 처음부터 다시
  돌지 않는다. 받은 record는 잃지도 겹치지도 않는다.
- 결정적 오류(404·파싱·스냅샷 불완전)와 일일 쿼터 소진은 다시 부르지 않는다.
- 429는 다시 부르되 ``Retry-After``를 존중하고, 너무 길면 이 run에서 기다리지 않는다.
- datagokr·krheritage·mois는 ``failure_kind``가 없지만 결과 코드 ``22``로 쿼터가 판정된다.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import pytest
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

from kortravelmap.dagster import provider_fetchers, upstream_retry
from kortravelmap.dagster.provider_fetchers import (
    fetch_kor_travel_concierge_youtube_features,
    fetch_krforest_recreation_forests,
    fetch_krheritage_events,
    fetch_krheritage_items,
    fetch_mcst_culture_records,
    fetch_seoul_open_data_bookstores,
    fetch_standard_special_streets,
    provider_call_retry_budget,
)
from kortravelmap.dagster.quota_exhaustion import quota_exhaustion_cause
from kortravelmap.dagster.upstream_retry import (
    MAX_UPSTREAM_RUN_RETRY_BUDGET,
    RetryBudget,
    retry_upstream_awaitable,
    sharing_run_retry_budget,
)
from kortravelmap.dagster.upstream_transient import (
    is_transient_upstream_failure,
    upstream_retry_after_seconds,
)

# ---------------------------------------------------------------- 공통 대역


def _provider_error(module: str, name: str, **attrs: Any) -> type[Exception]:
    """``module``(top-level 이름으로 판정된다) 소속의 provider 예외 타입을 만든다."""

    def _init(self: Exception, message: str = "", **kwargs: Any) -> None:
        Exception.__init__(self, message)
        for key, value in {**attrs, **kwargs}.items():
            setattr(self, key, value)

    return type(name, (Exception,), {"__module__": module, "__init__": _init})


_DatagokrTransportError = _provider_error(
    "datagokr.exceptions", "TransportError", status_code=None
)
_DatagokrApiError = _provider_error("datagokr.exceptions", "ApiErrorResponse", code="00")
_HeritageTransportError = _provider_error(
    "krheritage.exceptions", "TransportError", status_code=None, retryable=True
)
_HeritageApiError = _provider_error("krheritage.exceptions", "ApiErrorResponse", code="00")
_MoisServerError = _provider_error("mois.exceptions", "MoisServerError", result_code=None)
_MoisRequestError = _provider_error("mois.exceptions", "MoisRequestError", result_code=None)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """async 경계의 backoff를 즉시 끝내고 대기 길이만 기록한다."""

    recorded: list[float] = []

    async def _instant(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr(upstream_retry, "asyncio", SimpleNamespace(sleep=_instant))
    return recorded


def _settings(**overrides: Any) -> KorTravelMapSettings:
    return KorTravelMapSettings(data_go_kr_service_key=SecretStr("svc"), **overrides)


def _http_status_error(status: int, *, headers: dict[str, str] | None = None) -> Exception:
    request = httpx.Request("GET", "https://upstream.invalid/x")
    response = httpx.Response(status, request=request, headers=headers or {})
    return httpx.HTTPStatusError("boom", request=request, response=response)


# ---------------------------------------------------------------- 분류


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_http_status_error(503), True),
        (_http_status_error(502), True),
        (_http_status_error(504), True),
        (_http_status_error(429), True),
        (_http_status_error(404), False),
        (_http_status_error(401), False),
        (_http_status_error(501), False),
        (httpx.ConnectError("refused"), True),
        (httpx.ReadTimeout("slow"), True),
        (TimeoutError(), True),
        (ConnectionResetError(), True),
        (_DatagokrTransportError("after 3 attempts"), True),
        (_DatagokrTransportError("HTTP 404", status_code=404), False),
        (_DatagokrTransportError("HTTP 503", status_code=503), True),
        (_HeritageTransportError("HTTP 410", status_code=410), False),
        (_HeritageTransportError("body too large", retryable=False), False),
        (_MoisServerError("HTTP 502"), True),
        (_MoisRequestError("HTTP 400"), False),
        (ValueError("parse"), False),
        (RuntimeError("unclassified"), False),
    ],
)
def test_transient_classification(exc: Exception, expected: bool) -> None:
    assert is_transient_upstream_failure(exc) is expected


def test_lib_failure_kind_beats_its_http_200_status() -> None:
    """visitkorea·krforest는 결과 코드 오류에도 ``status_code=200``을 싣는다 — 200은 판정에서
    빠진다."""

    server = _provider_error("visitkorea.exceptions", "TourApiServerError")(
        "resultCode 99", status_code=200, failure_kind="server"
    )
    parse = _provider_error("visitkorea.exceptions", "TourApiParseError")(
        "bad", status_code=200, failure_kind="parse"
    )
    assert is_transient_upstream_failure(server) is True
    assert is_transient_upstream_failure(parse) is False


def test_rate_limit_without_http_status_is_the_daily_quota_not_a_throttle() -> None:
    quota = _provider_error("krforest.exceptions", "ForestRateLimitError")(
        "22", failure_kind="rate_limit", result_code="22"
    )
    throttle = _provider_error("krforest.exceptions", "ForestRateLimitError")(
        "HTTP 429", failure_kind="rate_limit", status_code=429
    )
    assert is_transient_upstream_failure(quota) is False
    assert is_transient_upstream_failure(throttle) is True


def test_wrapped_network_error_is_followed_through_the_explicit_cause() -> None:
    """mois는 다운로드 중 httpx 오류를 ``MoisRequestError(...) from exc``로 감싼다."""

    wrapped = _MoisRequestError("localdata download failed: x")
    wrapped.__cause__ = httpx.ReadError("reset")
    assert is_transient_upstream_failure(wrapped) is True


def test_implicit_context_is_not_followed() -> None:
    outer = ValueError("parse failed while handling")
    outer.__context__ = httpx.ReadError("reset")
    assert is_transient_upstream_failure(outer) is False


def test_retry_after_is_read_from_header_and_attributes() -> None:
    throttled = _http_status_error(429, headers={"Retry-After": "7"})
    assert upstream_retry_after_seconds(throttled) == 7.0
    assert upstream_retry_after_seconds(_http_status_error(503)) is None
    attr = _provider_error("x.y", "Throttled")("slow down", retry_after=3)
    assert upstream_retry_after_seconds(attr) == 3.0
    bad = _provider_error("x.y", "Throttled")("slow down", retry_after="soon")
    assert upstream_retry_after_seconds(bad) is None
    dated = _http_status_error(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
    assert upstream_retry_after_seconds(dated) == 0.0  # 지난 시각은 "지금"이다


# ---------------------------------------------------------------- 쿼터(결과 코드)


@pytest.mark.parametrize(
    "exc",
    [
        _DatagokrApiError("22: LIMITED", code="22"),
        _HeritageApiError("22: LIMITED", code="22"),
        _MoisRequestError("OpenAPI resultCode=22", result_code="22"),
        _HeritageApiError(
            "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
            code="LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
        ),
    ],
)
def test_result_code_22_is_daily_quota_for_libs_without_failure_kind(exc: Exception) -> None:
    assert quota_exhaustion_cause(exc) is exc
    assert is_transient_upstream_failure(exc) is False


def test_result_code_quota_is_module_qualified() -> None:
    """``code``는 흔한 속성 이름이다 — 선언한 lib 밖의 22는 쿼터가 아니다."""

    impostor = _provider_error("somewhere.else", "ApiErrorResponse")("22", code="22")
    assert quota_exhaustion_cause(impostor) is None


def test_other_result_codes_and_http_429_are_not_daily_quota() -> None:
    assert quota_exhaustion_cause(_DatagokrApiError("30: key", code="30")) is None
    assert quota_exhaustion_cause(_MoisRequestError("HTTP 400", result_code="10")) is None
    assert (
        quota_exhaustion_cause(_DatagokrTransportError("HTTP 429", status_code=429)) is None
    )


def test_real_datagokr_api_error_with_code_22_is_daily_quota() -> None:
    exceptions = pytest.importorskip("datagokr.exceptions")
    quota = exceptions.ApiErrorResponse(
        code="22", message="LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"
    )
    assert quota_exhaustion_cause(quota) is quota
    network = exceptions.TransportError("HTTP transport failed after 3 attempts")
    assert is_transient_upstream_failure(network) is True
    gone = exceptions.TransportError("HTTP 404", status_code=404)
    assert is_transient_upstream_failure(gone) is False


def test_real_krheritage_and_mois_contracts() -> None:
    krheritage = pytest.importorskip("krheritage.exceptions")
    mois = pytest.importorskip("mois.exceptions")
    assert quota_exhaustion_cause(krheritage.ApiErrorResponse("22", "LIMITED")) is not None
    assert is_transient_upstream_failure(krheritage.TransportError("reset")) is True
    assert (
        is_transient_upstream_failure(krheritage.TransportError("HTTP 404", status_code=404))
        is False
    )
    assert quota_exhaustion_cause(mois.MoisRequestError("x", result_code="22")) is not None
    assert is_transient_upstream_failure(mois.MoisServerError("HTTP 503")) is True
    assert is_transient_upstream_failure(mois.MoisAuthError("x", result_code="30")) is False


# ---------------------------------------------------------------- 재시도 경계


class _Flaky:
    def __init__(self, errors: list[Exception], value: Any = "ok") -> None:
        self.errors = list(errors)
        self.value = value
        self.calls = 0

    async def __call__(self) -> Any:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.value


async def test_jitter_draws_within_half_to_full_backoff(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    drawn: list[tuple[float, float]] = []

    def _uniform(low: float, high: float) -> float:
        drawn.append((low, high))
        return low

    monkeypatch.setattr(upstream_retry.random, "uniform", _uniform)
    call = _Flaky([httpx.ConnectError("x")])
    assert (
        await retry_upstream_awaitable(
            call,
            label="t",
            is_retryable=is_transient_upstream_failure,
            base_delay=10.0,
            jitter=True,
        )
        == "ok"
    )
    assert drawn == [(5.0, 10.0)]
    assert sleeps == [5.0]


async def test_retry_after_raises_the_wait_floor(sleeps: list[float]) -> None:
    call = _Flaky([_http_status_error(429, headers={"Retry-After": "40"})])
    await retry_upstream_awaitable(
        call,
        label="t",
        is_retryable=is_transient_upstream_failure,
        base_delay=2.0,
        retry_after=upstream_retry_after_seconds,
    )
    assert sleeps == [40.0]


async def test_retry_after_longer_than_the_run_can_wait_is_not_retried(
    sleeps: list[float],
) -> None:
    budget = RetryBudget(limit=4)
    error = _http_status_error(429, headers={"Retry-After": "3600"})
    call = _Flaky([error])
    with pytest.raises(httpx.HTTPStatusError) as raised:
        await retry_upstream_awaitable(
            call,
            label="t",
            is_retryable=is_transient_upstream_failure,
            budget=budget,
            retry_after=upstream_retry_after_seconds,
        )
    assert raised.value is error
    assert call.calls == 1
    assert sleeps == []
    assert budget.used == 0  # 예산을 쓰지 않는다


def test_budget_widens_but_never_shrinks_or_exceeds_the_cap() -> None:
    budget = RetryBudget(limit=8)
    assert budget.widen_to(4).limit == 8
    assert budget.widen_to(20).limit == 20
    assert budget.widen_to(10_000).limit == MAX_UPSTREAM_RUN_RETRY_BUDGET
    with pytest.raises(ValueError, match="must be >= 0"):
        budget.widen_to(-1)


def test_fetchers_share_the_run_budget_instead_of_multiplying_it() -> None:
    settings = _settings()
    with sharing_run_retry_budget() as shared:
        first = provider_call_retry_budget(settings, expected_calls=5_000)
        second = provider_call_retry_budget(settings, expected_calls=14)
    assert first is shared
    assert second is shared
    assert shared.limit == MAX_UPSTREAM_RUN_RETRY_BUDGET
    # 경계 밖이면 비례 예산을 새로 만든다.
    assert provider_call_retry_budget(settings, expected_calls=14) is not shared


# ---------------------------------------------------------------- fetcher 적용처


class _FlakyEvents:
    def __init__(self, error: Exception) -> None:
        self.error: Exception | None = error
        self.calls: list[tuple[int, int]] = []

    async def by_month(self, *, year: int, month: int) -> tuple[object, ...]:
        self.calls.append((year, month))
        if len(self.calls) == 3 and self.error is not None:
            error, self.error = self.error, None
            raise error
        return (f"{year}-{month:02d}",)


class _HeritageClient:
    instances: list[_HeritageClient] = []
    error: Exception = httpx.ConnectError("x")
    detail_errors: list[Exception] = []

    def __init__(self, **_kwargs: Any) -> None:
        self.event = _FlakyEvents(type(self).error)
        self.detail_errors = list(type(self).detail_errors)
        self.detail_calls = 0
        self.search = SimpleNamespace(list=self._list, details=self._details)
        self.closed = False
        type(self).instances.append(self)

    async def _list(self, *, page_size: int, page: int, ccba_kdcd: str) -> Any:
        items = [
            SimpleNamespace(
                key=SimpleNamespace(ccba_kdcd=ccba_kdcd, ccba_asno=f"{i:04d}", ccba_ctcd="11"),
                name_ko=str(i),
            )
            for i in range(3)
        ]
        return SimpleNamespace(items=items if page == 1 else [], total=3)

    async def _details(self, kdcd: str, asno: str, ctcd: str) -> str:
        self.detail_calls += 1
        if asno == "0001" and self.detail_errors:
            raise self.detail_errors.pop(0)
        return f"{kdcd}/{asno}/{ctcd}"

    async def aclose(self) -> None:
        self.closed = True


def _install_krheritage(
    monkeypatch: pytest.MonkeyPatch,
    *,
    error: Exception | None = None,
    detail_errors: list[Exception] | None = None,
) -> type[_HeritageClient]:
    _HeritageClient.instances = []
    _HeritageClient.error = error if error is not None else httpx.ConnectError("x")
    _HeritageClient.detail_errors = detail_errors or []
    module = ModuleType("krheritage")
    module.__dict__["HeritageClient"] = _HeritageClient
    monkeypatch.setitem(sys.modules, "krheritage", module)
    return _HeritageClient


async def _collect(agen: AsyncIterator[Any]) -> list[Any]:
    return [item async for item in agen]


async def test_krheritage_events_retries_only_the_failing_month(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    client_type = _install_krheritage(
        monkeypatch, error=_HeritageTransportError("HTTP 503", status_code=503)
    )
    records = await _collect(fetch_krheritage_events(_settings()))

    client = client_type.instances[0]
    # 14개 달 + 실패한 세 번째 달의 재시도 1회. 처음부터 다시 돌지 않는다.
    assert len(client.event.calls) == 15
    assert client.event.calls[2] == client.event.calls[3]
    assert len(records) == 14
    assert len(set(records)) == 14
    assert len(sleeps) == 1
    assert client.closed is True


async def test_krheritage_events_does_not_retry_the_daily_quota(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    quota = _HeritageApiError("22: LIMITED", code="22")
    client_type = _install_krheritage(monkeypatch, error=quota)

    with pytest.raises(type(quota), match="LIMITED") as raised:
        await _collect(fetch_krheritage_events(_settings()))

    assert raised.value is quota
    assert len(client_type.instances[0].event.calls) == 3  # 실패한 달에서 멈춘다
    assert sleeps == []


async def test_krheritage_events_gives_up_after_two_attempts(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    calls: list[tuple[int, int]] = []

    class _AlwaysDown:
        async def by_month(self, *, year: int, month: int) -> tuple[object, ...]:
            calls.append((year, month))
            raise _HeritageTransportError("HTTP 503", status_code=503)

    class _Client(_HeritageClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.event = _AlwaysDown()  # type: ignore[assignment]

    module = ModuleType("krheritage")
    module.__dict__["HeritageClient"] = _Client
    monkeypatch.setitem(sys.modules, "krheritage", module)

    with pytest.raises(Exception, match="HTTP 503"):
        await _collect(fetch_krheritage_events(_settings()))
    assert len(calls) == 2  # 첫 달 2회 시도 뒤 원 예외 — 다음 달로 가지 않는다
    assert len(sleeps) == 1


async def test_krheritage_items_retries_a_single_detail(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    client_type = _install_krheritage(monkeypatch, detail_errors=[httpx.ReadTimeout("slow")])
    records = await _collect(fetch_krheritage_items(_settings(krheritage_kind_codes="11")))

    assert records == ["11/0000/11", "11/0001/11", "11/0002/11"]
    assert client_type.instances[0].detail_calls == 4
    assert len(sleeps) == 1


class _ForestPage:
    def __init__(self, items: list[object], total: int) -> None:
        self.items = items
        self.total_count = total


async def test_krforest_retries_one_page_of_a_paged_dataset(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    server_error = _provider_error("krforest.exceptions", "ForestServerError")(
        "HTTP 502", status_code=502, failure_kind="server"
    )
    calls: list[int] = []

    async def _endpoint(*, page_no: int, num_of_rows: int) -> _ForestPage:
        calls.append(page_no)
        if calls == [1, 2]:
            raise server_error
        rows = [f"r{page_no}-{i}" for i in range(num_of_rows)] if page_no <= 2 else []
        return _ForestPage(rows[:2] if page_no == 2 else rows, num_of_rows + 2)

    class _Client:
        def __init__(self, **_kwargs: Any) -> None:
            self.travel = SimpleNamespace(standard_recreation_forests=_endpoint)

        async def aclose(self) -> None:
            return None

    module = ModuleType("krforest")
    module.__dict__["ForestClient"] = _Client
    module.__dict__["ForestNoDataError"] = type("ForestNoDataError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "krforest", module)

    records = await _collect(fetch_krforest_recreation_forests(_settings()))

    assert calls == [1, 2, 2]
    assert len(records) == 1002
    assert len(set(records)) == 1002
    assert len(sleeps) == 1


async def test_standard_file_is_reread_whole_without_duplicate_rows(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    class _FileService:
        def __init__(self) -> None:
            self.reads = 0

        async def iter_file_pages(self) -> AsyncIterator[Any]:
            self.reads += 1
            yield SimpleNamespace(items=["a", "b"], total_count=4)
            if self.reads == 1:
                raise _DatagokrTransportError("HTTP transport failed after 3 attempts")
            yield SimpleNamespace(items=["c", "d"], total_count=4)

    service = _FileService()

    class _Client:
        def __init__(self, **_kwargs: Any) -> None:
            self.special_street = service

        async def aclose(self) -> None:
            return None

    module = ModuleType("datagokr")
    module.__dict__["DataGoKrClient"] = _Client
    monkeypatch.setitem(sys.modules, "datagokr", module)

    records = await _collect(fetch_standard_special_streets(_settings()))

    assert records == ["a", "b", "c", "d"]
    assert service.reads == 2
    assert len(sleeps) == 1


def _mock_async_client(
    monkeypatch: pytest.MonkeyPatch, handler: Any
) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    real = httpx.AsyncClient

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        response: httpx.Response = handler(request, len(seen))
        return response

    def _factory(**kwargs: Any) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(_handler), **kwargs)

    monkeypatch.setattr(provider_fetchers.httpx, "AsyncClient", _factory)
    return seen


async def test_seoul_bookstores_retry_a_503_page_without_leaking_the_key(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], caplog: pytest.LogCaptureFixture
) -> None:
    def _respond(_request: httpx.Request, count: int) -> httpx.Response:
        if count == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "TbSlibBookstoreInfo": {
                    "list_total_count": 2,
                    "RESULT": {"CODE": "INFO-000"},
                    "row": [{"id": 1}, {"id": 2}],
                }
            },
        )

    seen = _mock_async_client(monkeypatch, _respond)
    settings = KorTravelMapSettings(seoul_open_data_api_key=SecretStr("sekret-key"))

    rows = await _collect(fetch_seoul_open_data_bookstores(settings))

    assert rows == [{"id": 1}, {"id": 2}]
    assert len(seen) == 2
    assert len(sleeps) == 1
    assert "sekret-key" not in caplog.text


async def test_seoul_bookstores_do_not_retry_a_404(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    seen = _mock_async_client(monkeypatch, lambda _r, _c: httpx.Response(404))
    settings = KorTravelMapSettings(seoul_open_data_api_key=SecretStr("k"))

    with pytest.raises(provider_fetchers.SeoulOpenDataError, match="HTTP 404"):
        await _collect(fetch_seoul_open_data_bookstores(settings))
    assert len(seen) == 1
    assert sleeps == []


async def test_concierge_export_retries_one_page(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    def _respond(request: httpx.Request, count: int) -> httpx.Response:
        if count == 2:
            return httpx.Response(502)
        if "cursor" not in request.url.params:
            return httpx.Response(200, json={"items": [1], "has_more": True, "next_cursor": "c1"})
        return httpx.Response(200, json={"items": [2], "has_more": False})

    seen = _mock_async_client(monkeypatch, _respond)
    settings = KorTravelMapSettings(
        kor_travel_concierge_base_url="https://concierge.invalid",
        kor_travel_concierge_api_key=SecretStr("k"),
        kor_travel_concierge_feature_cursor=None,
    )

    items = await _collect(fetch_kor_travel_concierge_youtube_features(settings))

    assert items == [1, 2]
    assert [request.url.params.get("cursor") for request in seen] == [None, "c1", "c1"]
    assert len(sleeps) == 1


async def test_mcst_retries_a_slug_download_once_without_duplicate_rows(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    from kortravelmap.providers.mcst import MCST_FILE_DATASETS, McstSlugAttempt

    slug = next(iter(MCST_FILE_DATASETS))
    network_error = _provider_error("mcst.exceptions", "McstNetworkError")("reset")
    attempts: list[int] = []

    class _Client:
        def __init__(self, **_kwargs: Any) -> None:
            return None

        async def iter_csv(self, requested: str) -> AsyncIterator[dict[str, str]]:
            attempts.append(1)
            yield {"slug": requested, "row": "1"}
            if len(attempts) == 1:
                raise network_error
            yield {"slug": requested, "row": "2"}

        async def aclose(self) -> None:
            return None

    module = ModuleType("mcst")
    module.__dict__["FileDataClient"] = _Client
    module.__dict__["McstNetworkError"] = type(network_error)
    monkeypatch.setitem(sys.modules, "mcst", module)

    items = await _collect(fetch_mcst_culture_records(_settings(), slugs=[slug]))

    assert isinstance(items[0], McstSlugAttempt)
    assert items[1:] == [(slug, {"slug": slug, "row": "1"}), (slug, {"slug": slug, "row": "2"})]
    assert len(attempts) == 2
    assert len(sleeps) == 1


def test_mois_localdata_sync_retries_only_the_failing_slug(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.dagster.mois_source_sync import sync_mois_source_db

    slugs_called: list[str] = []

    class _Result:
        def __init__(self, slugs: tuple[str, ...]) -> None:
            self.service_slugs = slugs
            self.sync_kind = "localdata_full"
            self.scanned_count = self.upserted_count = self.open_count = 1
            self.closed_count = self.unknown_status_count = 0

    async def _sync(session: Any, client: Any, *, service_slugs: Any, **_kw: Any) -> _Result:
        await session.run_sync(lambda _s: None)
        slug = tuple(service_slugs)[0]
        slugs_called.append(slug)
        if slugs_called == ["a", "b"]:
            raise _MoisServerError("localdata download b: HTTP 503")
        return _Result((slug,))

    class _FileClient:
        def __init__(self, **_kwargs: Any) -> None:
            return None

        async def aclose(self) -> None:
            return None

    module = ModuleType("mois")
    module.__dict__["create_sqlite_schema"] = lambda engine, **_kw: True
    module.__dict__["LocalDataFileClient"] = _FileClient
    module.__dict__["sync_localdata_source_db"] = _sync
    monkeypatch.setitem(sys.modules, "mois", module)
    recorded: list[float] = []

    async def _instant(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr(upstream_retry, "asyncio", SimpleNamespace(sleep=_instant))
    settings = KorTravelMapSettings(mois_source_db_path=str(tmp_path / "m.sqlite"))

    summary = sync_mois_source_db(settings, service_slugs=["a", "b", "c"])

    assert slugs_called == ["a", "b", "b", "c"]
    assert summary.service_slugs == ("a", "b", "c")
    assert len(recorded) == 1
