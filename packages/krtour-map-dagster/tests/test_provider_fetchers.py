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
