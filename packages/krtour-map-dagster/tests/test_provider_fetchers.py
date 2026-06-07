"""Provider public client live fetcher + live resource 단위 테스트 (T-RV-04b)."""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Iterator
from types import ModuleType
from typing import Any, cast

import pytest
from dagster import build_init_resource_context
from krtour.map.settings import KrtourMapSettings
from pydantic import SecretStr

from krtour.map_dagster.provider_fetchers import (
    ProviderCredentialMissing,
    fetch_datagokr_cultural_festivals,
    fetch_krex_rest_areas,
    fetch_krex_traffic_notices,
    fetch_krheritage_events,
)
from krtour.map_dagster.resources import (
    PROVIDER_RECORD_RESOURCE_DEFINITIONS,
    PROVIDER_RECORD_RESOURCE_SPECS,
    build_provider_record_guard_resource,
    build_provider_record_live_resource,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)


_DATAGOKR_SPEC = {
    spec.resource_key: spec for spec in PROVIDER_RECORD_RESOURCE_SPECS
}["datagokr_cultural_festivals"]


class _FakeFestivalService:
    def __init__(self, records: list[object]) -> None:
        self._records = records

    def iter_all(self, **_filters: Any) -> Iterator[object]:
        yield from self._records


class _FakeDataGoKrClient:
    instances: list[_FakeDataGoKrClient] = []

    def __init__(self, *, api_key: str | None = None, **_kwargs: Any) -> None:
        self.api_key = api_key
        self.closed = False
        self.festival = _FakeFestivalService([object(), object()])
        _FakeDataGoKrClient.instances.append(self)

    def close(self) -> None:
        self.closed = True


def _install_fake_datagokr(monkeypatch: pytest.MonkeyPatch) -> type[_FakeDataGoKrClient]:
    _FakeDataGoKrClient.instances = []
    module = ModuleType("datagokr")
    module.__dict__["DataGoKrClient"] = _FakeDataGoKrClient
    monkeypatch.setitem(sys.modules, "datagokr", module)
    return _FakeDataGoKrClient


class _FakeEventService:
    def __init__(self, records: list[object]) -> None:
        self._records = records

    def iter_months(self, **_filters: Any) -> Iterator[object]:
        yield from self._records


class _FakeHeritageClient:
    instances: list[_FakeHeritageClient] = []

    def __init__(self, *, api_key: str | None = None, **_kwargs: Any) -> None:
        self.api_key = api_key
        self.closed = False
        self.event = _FakeEventService([object(), object()])
        _FakeHeritageClient.instances.append(self)

    def close(self) -> None:
        self.closed = True


def _install_fake_krheritage(monkeypatch: pytest.MonkeyPatch) -> type[_FakeHeritageClient]:
    _FakeHeritageClient.instances = []
    module = ModuleType("krheritage")
    module.__dict__["HeritageClient"] = _FakeHeritageClient
    monkeypatch.setitem(sys.modules, "krheritage", module)
    return _FakeHeritageClient


class _FakePage:
    def __init__(
        self, *, items: tuple[object, ...], total_count: int, page_no: int
    ) -> None:
        self.items = items
        self.total_count = total_count
        self.page_no = page_no


class _FakeRestareaService:
    def __init__(self, total: int) -> None:
        self.total = total
        self.calls: list[tuple[int, int]] = []

    def list_all(
        self, *, num_of_rows: int = 1000, page_no: int = 1, **_kwargs: Any
    ) -> _FakePage:
        self.calls.append((num_of_rows, page_no))
        start = (page_no - 1) * num_of_rows
        end = min(start + num_of_rows, self.total)
        items = tuple(object() for _ in range(max(0, end - start)))
        return _FakePage(items=items, total_count=self.total, page_no=page_no)


class _FakeKrexClient:
    instances: list[_FakeKrexClient] = []
    total: int = 0

    def __init__(self, *, go_api_key: str | None = None, **_kwargs: Any) -> None:
        self.go_api_key = go_api_key
        self.closed = False
        self.restarea = _FakeRestareaService(type(self).total)
        _FakeKrexClient.instances.append(self)

    def close(self) -> None:
        self.closed = True


def _install_fake_krex(
    monkeypatch: pytest.MonkeyPatch, *, total: int
) -> type[_FakeKrexClient]:
    _FakeKrexClient.instances = []
    _FakeKrexClient.total = total
    module = ModuleType("krex")
    module.__dict__["KrexClient"] = _FakeKrexClient
    monkeypatch.setitem(sys.modules, "krex", module)
    return _FakeKrexClient


def test_krex_rest_areas_fetch_raises_when_credential_missing() -> None:
    settings = KrtourMapSettings(krex_go_api_key=None)

    generator = fetch_krex_rest_areas(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_krex_rest_areas_fetch_paginates_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # total 1003 → page1=1000(full)·page2=3(short) → 2 pages, short-page stop.
    fake = _install_fake_krex(monkeypatch, total=1003)
    settings = KrtourMapSettings(krex_go_api_key=SecretStr("go-key"))

    records = list(fetch_krex_rest_areas(settings))

    assert len(records) == 1003
    assert len(fake.instances) == 1
    client = fake.instances[0]
    assert client.go_api_key == "go-key"
    assert client.closed is True
    # 페이지네이션: page_no 1,2 만 호출(빈 3페이지 미호출), num_of_rows=1000.
    assert client.restarea.calls == [(1000, 1), (1000, 2)]


def test_krex_rest_areas_fetch_stops_on_total_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # total 2000 = 정확히 2 페이지(각 1000) → total_count 도달로 stop(빈 페이지 X).
    fake = _install_fake_krex(monkeypatch, total=2000)
    settings = KrtourMapSettings(krex_go_api_key=SecretStr("go-key"))

    records = list(fetch_krex_rest_areas(settings))

    assert len(records) == 2000
    assert fake.instances[0].restarea.calls == [(1000, 1), (1000, 2)]
    assert fake.instances[0].closed is True


def test_krex_rest_areas_fetch_closes_on_partial_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_krex(monkeypatch, total=1003)
    settings = KrtourMapSettings(krex_go_api_key=SecretStr("go-key"))

    generator = fetch_krex_rest_areas(settings)
    first = next(generator)
    assert first is not None
    generator.close()

    assert fake.instances[0].closed is True


class _FakeIncidentService:
    def __init__(self, total: int) -> None:
        self.total = total
        self.calls: list[tuple[int, int]] = []

    def incident(
        self, *, num_of_rows: int = 1000, page_no: int = 1, **_kwargs: Any
    ) -> _FakePage:
        self.calls.append((num_of_rows, page_no))
        start = (page_no - 1) * num_of_rows
        end = min(start + num_of_rows, self.total)
        items = tuple(object() for _ in range(max(0, end - start)))
        return _FakePage(items=items, total_count=self.total, page_no=page_no)


class _FakeKrexTrafficClient:
    instances: list[_FakeKrexTrafficClient] = []
    total: int = 0

    def __init__(self, *, ex_api_key: str | None = None, **_kwargs: Any) -> None:
        self.ex_api_key = ex_api_key
        self.closed = False
        self.traffic = _FakeIncidentService(type(self).total)
        _FakeKrexTrafficClient.instances.append(self)

    def close(self) -> None:
        self.closed = True


def _install_fake_krex_traffic(
    monkeypatch: pytest.MonkeyPatch, *, total: int
) -> type[_FakeKrexTrafficClient]:
    _FakeKrexTrafficClient.instances = []
    _FakeKrexTrafficClient.total = total
    module = ModuleType("krex")
    module.__dict__["KrexClient"] = _FakeKrexTrafficClient
    monkeypatch.setitem(sys.modules, "krex", module)
    return _FakeKrexTrafficClient


def test_krex_traffic_notices_fetch_raises_when_credential_missing() -> None:
    settings = KrtourMapSettings(krex_ex_api_key=None)

    generator = fetch_krex_traffic_notices(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_krex_traffic_notices_fetch_paginates_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # total 1003 → page1=1000(full)·page2=3(short) → 2 pages, short-page stop.
    fake = _install_fake_krex_traffic(monkeypatch, total=1003)
    settings = KrtourMapSettings(krex_ex_api_key=SecretStr("ex-key"))

    records = list(fetch_krex_traffic_notices(settings))

    assert len(records) == 1003
    assert len(fake.instances) == 1
    client = fake.instances[0]
    assert client.ex_api_key == "ex-key"
    assert client.closed is True
    # 페이지네이션: page_no 1,2 만 호출(빈 3페이지 미호출), num_of_rows=1000.
    assert client.traffic.calls == [(1000, 1), (1000, 2)]


def test_krex_traffic_notices_fetch_stops_on_total_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # total 2000 = 정확히 2 페이지(각 1000) → total_count 도달로 stop(빈 페이지 X).
    fake = _install_fake_krex_traffic(monkeypatch, total=2000)
    settings = KrtourMapSettings(krex_ex_api_key=SecretStr("ex-key"))

    records = list(fetch_krex_traffic_notices(settings))

    assert len(records) == 2000
    assert fake.instances[0].traffic.calls == [(1000, 1), (1000, 2)]
    assert fake.instances[0].closed is True


def test_krex_traffic_notices_fetch_closes_on_partial_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_krex_traffic(monkeypatch, total=1003)
    settings = KrtourMapSettings(krex_ex_api_key=SecretStr("ex-key"))

    generator = fetch_krex_traffic_notices(settings)
    first = next(generator)
    assert first is not None
    generator.close()

    assert fake.instances[0].closed is True


def test_fetch_raises_when_credential_missing() -> None:
    settings = KrtourMapSettings(data_go_kr_service_key=None)

    generator = fetch_datagokr_cultural_festivals(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_fetch_yields_records_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_datagokr(monkeypatch)
    settings = KrtourMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = list(fetch_datagokr_cultural_festivals(settings))

    assert len(records) == 2
    assert len(fake.instances) == 1
    client = fake.instances[0]
    assert client.api_key == "service-key"
    assert client.closed is True


def test_fetch_closes_client_on_partial_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_datagokr(monkeypatch)
    settings = KrtourMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    generator = fetch_datagokr_cultural_festivals(settings)
    first = next(generator)
    assert first is not None
    generator.close()

    assert fake.instances[0].closed is True


def test_krheritage_fetch_raises_when_credential_missing() -> None:
    settings = KrtourMapSettings(data_go_kr_service_key=None)

    generator = fetch_krheritage_events(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_krheritage_fetch_yields_records_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_krheritage(monkeypatch)
    settings = KrtourMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = list(fetch_krheritage_events(settings))

    assert len(records) == 2
    assert len(fake.instances) == 1
    client = fake.instances[0]
    assert client.api_key == "service-key"
    assert client.closed is True


def test_live_resource_returns_iterable_when_credentials_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY", "service-key")
    sentinel = [object(), object()]

    def _fake_fetch(_settings: KrtourMapSettings) -> Iterable[Any]:
        return sentinel

    resource_def = build_provider_record_live_resource(_DATAGOKR_SPEC, _fake_fetch)
    resource_fn = cast("Callable[[object], object]", resource_def.resource_fn)

    result = resource_fn(build_init_resource_context())

    assert result is sentinel


def test_live_resource_raises_guard_message_when_credentials_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY", raising=False)

    def _fake_fetch(_settings: KrtourMapSettings) -> Iterable[Any]:  # pragma: no cover
        raise AssertionError("fetch must not run when credentials are missing")

    resource_def = build_provider_record_live_resource(_DATAGOKR_SPEC, _fake_fetch)
    resource_fn = cast("Callable[[object], object]", resource_def.resource_fn)

    with pytest.raises(RuntimeError) as exc_info:
        resource_fn(build_init_resource_context())

    message = str(exc_info.value)
    assert "KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY" in message
    assert "credential" in message


def test_datagokr_resource_definition_is_live_not_guard() -> None:
    live = PROVIDER_RECORD_RESOURCE_DEFINITIONS["datagokr_cultural_festivals"]
    guard = build_provider_record_guard_resource(_DATAGOKR_SPEC)

    assert live.description is not None
    assert "live fetcher" in live.description
    assert "live fetcher" not in (guard.description or "")
    # 다른 provider는 여전히 guard로 남는다.
    opinet = PROVIDER_RECORD_RESOURCE_DEFINITIONS["opinet_stations"]
    assert "guard" in (opinet.description or "")
