"""Provider public client live fetcher + live resource 단위 테스트 (T-RV-04b)."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from types import ModuleType
from typing import Any, cast

import pytest
from dagster import build_init_resource_context
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

import kortravelmap.dagster.provider_fetchers as provider_fetchers
from kortravelmap.dagster.provider_fetchers import (
    ProviderCredentialMissing,
    fetch_airkorea_air_quality,
    fetch_airkorea_stations,
    fetch_datagokr_cultural_festivals,
    fetch_khoa_beaches,
    fetch_knps_geometry_records,
    fetch_knps_point_records,
    fetch_kor_travel_concierge_youtube_features,
    fetch_krairport_airports,
    fetch_krex_rest_area_fuel_prices,
    fetch_krex_rest_areas,
    fetch_krex_traffic_notices,
    fetch_krforest_arboretums,
    fetch_krforest_recreation_forests,
    fetch_krheritage_events,
    fetch_krheritage_items,
    fetch_mois_license_records,
    fetch_opinet_station_price_details,
    fetch_opinet_stations,
    fetch_standard_museums,
    fetch_standard_parking_lots,
    fetch_standard_tourist_attractions,
    fetch_visitkorea_festival_events,
)
from kortravelmap.dagster.resources import (
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


class _FakeKrtourAiAgentResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeKrtourAiAgentAsyncClient:
    payloads: list[dict[str, Any]] = []
    instances: list[_FakeKrtourAiAgentAsyncClient] = []

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float,
        headers: dict[str, str],
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.headers = headers
        self.calls: list[tuple[str, dict[str, str | int]]] = []
        self.closed = False
        _FakeKrtourAiAgentAsyncClient.instances.append(self)

    async def __aenter__(self) -> _FakeKrtourAiAgentAsyncClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.closed = True

    async def get(
        self,
        path: str,
        *,
        params: dict[str, str | int],
    ) -> _FakeKrtourAiAgentResponse:
        self.calls.append((path, dict(params)))
        index = len(self.calls) - 1
        return _FakeKrtourAiAgentResponse(type(self).payloads[index])


def _install_fake_kor_travel_concierge_httpx(
    monkeypatch: pytest.MonkeyPatch,
    payloads: list[dict[str, Any]],
) -> type[_FakeKrtourAiAgentAsyncClient]:
    _FakeKrtourAiAgentAsyncClient.payloads = payloads
    _FakeKrtourAiAgentAsyncClient.instances = []
    monkeypatch.setattr(
        provider_fetchers.httpx,
        "AsyncClient",
        _FakeKrtourAiAgentAsyncClient,
    )
    return _FakeKrtourAiAgentAsyncClient


class _FakeFestivalService:
    def __init__(self, records: list[object]) -> None:
        self._records = records

    def iter_all(self, **_filters: Any) -> Iterator[object]:
        yield from self._records


class _FakeMuseumArtService:
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
        self.museum_art = _FakeMuseumArtService([object(), object(), object()])
        self.tourist_attraction = _FakeMuseumArtService([object(), object()])
        self.parking = _FakeMuseumArtService([object(), object(), object(), object()])
        _FakeDataGoKrClient.instances.append(self)

    def close(self) -> None:
        self.closed = True


def _install_fake_datagokr(monkeypatch: pytest.MonkeyPatch) -> type[_FakeDataGoKrClient]:
    _FakeDataGoKrClient.instances = []
    module = ModuleType("datagokr")
    module.__dict__["DataGoKrClient"] = _FakeDataGoKrClient
    monkeypatch.setitem(sys.modules, "datagokr", module)
    return _FakeDataGoKrClient


async def test_kor_travel_concierge_youtube_fetch_paginates_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_kor_travel_concierge_httpx(
        monkeypatch,
        [
            {"items": [{"id": 1}], "next_cursor": "c2", "has_more": True},
            {"items": [{"id": 2}], "next_cursor": None, "has_more": False},
        ],
    )
    settings = KorTravelMapSettings(
        kor_travel_concierge_base_url="https://kor-travel-concierge.example",
        kor_travel_concierge_api_key=SecretStr("agent-key"),
    )

    records = [
        item async for item in fetch_kor_travel_concierge_youtube_features(settings)
    ]

    assert records == [{"id": 1}, {"id": 2}]
    assert len(fake.instances) == 1
    client = fake.instances[0]
    assert client.base_url == "https://kor-travel-concierge.example"
    assert client.headers == {"X-API-Key": "agent-key"}
    assert client.closed is True
    assert client.calls == [
        ("/api/v1/features/snapshot", {"limit": 200}),
        ("/api/v1/features/snapshot", {"limit": 200, "cursor": "c2"}),
    ]


async def test_kor_travel_concierge_youtube_fetch_changes_uses_initial_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_kor_travel_concierge_httpx(
        monkeypatch,
        [{"items": [], "next_cursor": None, "has_more": False}],
    )
    settings = KorTravelMapSettings(
        kor_travel_concierge_base_url="https://kor-travel-concierge.example/",
        kor_travel_concierge_api_key=SecretStr("agent-key"),
        kor_travel_concierge_feature_sync_endpoint="changes",
        kor_travel_concierge_feature_cursor="cursor-1",
        kor_travel_concierge_feature_page_size=50,
    )

    records = [
        item async for item in fetch_kor_travel_concierge_youtube_features(settings)
    ]

    assert records == []
    assert fake.instances[0].base_url == "https://kor-travel-concierge.example"
    assert fake.instances[0].calls == [
        (
            "/api/v1/features/changes",
            {"limit": 50, "cursor": "cursor-1"},
        )
    ]


async def test_kor_travel_concierge_youtube_fetch_raises_when_credential_missing() -> None:
    generator = fetch_kor_travel_concierge_youtube_features(
        KorTravelMapSettings(
            kor_travel_concierge_base_url=None,
            kor_travel_concierge_api_key=SecretStr("agent-key"),
        )
    )

    with pytest.raises(ProviderCredentialMissing):
        await anext(generator)


async def test_kor_travel_concierge_youtube_fetch_raises_on_non_advancing_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-06 — has_more=true인데 next_cursor가 직전 cursor와 같으면(stall) RuntimeError."""
    _install_fake_kor_travel_concierge_httpx(
        monkeypatch,
        [
            {"items": [{"id": 1}], "next_cursor": "c2", "has_more": True},
            {"items": [{"id": 2}], "next_cursor": "c2", "has_more": True},
        ],
    )
    settings = KorTravelMapSettings(
        kor_travel_concierge_base_url="https://kor-travel-concierge.example",
        kor_travel_concierge_api_key=SecretStr("agent-key"),
    )

    with pytest.raises(RuntimeError, match="이전 cursor와 같다"):
        [item async for item in fetch_kor_travel_concierge_youtube_features(settings)]


async def test_kor_travel_concierge_youtube_fetch_raises_on_missing_next_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-06 — has_more=true인데 next_cursor가 없으면(None/빈 문자열) RuntimeError."""
    _install_fake_kor_travel_concierge_httpx(
        monkeypatch,
        [{"items": [{"id": 1}], "next_cursor": None, "has_more": True}],
    )
    settings = KorTravelMapSettings(
        kor_travel_concierge_base_url="https://kor-travel-concierge.example",
        kor_travel_concierge_api_key=SecretStr("agent-key"),
    )

    with pytest.raises(RuntimeError, match="next_cursor가 없다"):
        [item async for item in fetch_kor_travel_concierge_youtube_features(settings)]


class _FakeEventService:
    def __init__(self, records: list[object]) -> None:
        self._records = records

    def iter_months(self, **_filters: Any) -> Iterator[object]:
        yield from self._records


class _FakeHeritageSearchService:
    def __init__(self, details_by_kind: dict[str, list[object]]) -> None:
        self._details_by_kind = details_by_kind
        self.calls: list[tuple[int, str]] = []

    def iter_all_details(
        self, *, page_size: int = 100, **filters: Any
    ) -> Iterator[object]:
        kind_code = str(filters.get("ccba_kdcd", ""))
        self.calls.append((page_size, kind_code))
        yield from self._details_by_kind.get(kind_code, [])


class _FakeHeritageClient:
    instances: list[_FakeHeritageClient] = []
    details_by_kind: dict[str, list[object]] = {}

    def __init__(self, *, api_key: str | None = None, **_kwargs: Any) -> None:
        self.api_key = api_key
        self.closed = False
        self.event = _FakeEventService([object(), object()])
        self.search = _FakeHeritageSearchService(type(self).details_by_kind)
        _FakeHeritageClient.instances.append(self)

    def close(self) -> None:
        self.closed = True


def _install_fake_krheritage(
    monkeypatch: pytest.MonkeyPatch,
    *,
    details_by_kind: dict[str, list[object]] | None = None,
) -> type[_FakeHeritageClient]:
    _FakeHeritageClient.instances = []
    _FakeHeritageClient.details_by_kind = details_by_kind or {}
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

    def fuel_prices(
        self, *, num_of_rows: int = 1000, page_no: int = 1, **_kwargs: Any
    ) -> _FakePage:
        return self.list_all(num_of_rows=num_of_rows, page_no=page_no)


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
    settings = KorTravelMapSettings(krex_go_api_key=None)

    generator = fetch_krex_rest_areas(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_krex_rest_areas_fetch_paginates_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # total 1003 → page1=1000(full)·page2=3(short) → 2 pages, short-page stop.
    fake = _install_fake_krex(monkeypatch, total=1003)
    settings = KorTravelMapSettings(krex_go_api_key=SecretStr("go-key"))

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
    settings = KorTravelMapSettings(krex_go_api_key=SecretStr("go-key"))

    records = list(fetch_krex_rest_areas(settings))

    assert len(records) == 2000
    assert fake.instances[0].restarea.calls == [(1000, 1), (1000, 2)]
    assert fake.instances[0].closed is True


def test_krex_rest_areas_fetch_closes_on_partial_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_krex(monkeypatch, total=1003)
    settings = KorTravelMapSettings(krex_go_api_key=SecretStr("go-key"))

    generator = fetch_krex_rest_areas(settings)
    first = next(generator)
    assert first is not None
    generator.close()

    assert fake.instances[0].closed is True


def test_krex_rest_area_fuel_prices_missing_key_raises() -> None:
    settings = KorTravelMapSettings(krex_ex_api_key=None)

    generator = fetch_krex_rest_area_fuel_prices(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_krex_rest_area_fuel_prices_fetch_paginates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_krex(monkeypatch, total=1003)
    settings = KorTravelMapSettings(krex_ex_api_key=SecretStr("ex-key"))

    records = list(fetch_krex_rest_area_fuel_prices(settings))

    assert len(records) == 1003
    assert fake.instances[0].restarea.calls == [(1000, 1), (1000, 2)]
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
    settings = KorTravelMapSettings(krex_ex_api_key=None)

    generator = fetch_krex_traffic_notices(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_krex_traffic_notices_fetch_paginates_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # total 1003 → page1=1000(full)·page2=3(short) → 2 pages, short-page stop.
    fake = _install_fake_krex_traffic(monkeypatch, total=1003)
    settings = KorTravelMapSettings(krex_ex_api_key=SecretStr("ex-key"))

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
    settings = KorTravelMapSettings(krex_ex_api_key=SecretStr("ex-key"))

    records = list(fetch_krex_traffic_notices(settings))

    assert len(records) == 2000
    assert fake.instances[0].traffic.calls == [(1000, 1), (1000, 2)]
    assert fake.instances[0].closed is True


def test_krex_traffic_notices_fetch_closes_on_partial_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_krex_traffic(monkeypatch, total=1003)
    settings = KorTravelMapSettings(krex_ex_api_key=SecretStr("ex-key"))

    generator = fetch_krex_traffic_notices(settings)
    first = next(generator)
    assert first is not None
    generator.close()

    assert fake.instances[0].closed is True


def test_mois_fetch_raises_when_source_db_unset() -> None:
    settings = KorTravelMapSettings(mois_source_db_path=None)

    generator = fetch_mois_license_records(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_mois_fetch_raises_when_source_db_file_missing(tmp_path: Any) -> None:
    missing = tmp_path / "does-not-exist.sqlite"
    settings = KorTravelMapSettings(mois_source_db_path=str(missing))

    generator = fetch_mois_license_records(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_mois_fetch_yields_open_records_and_cleans_up(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    mois_db = pytest.importorskip("mois.db")
    from kortravelmap.providers.mois import PROMOTED_SERVICE_SLUGS
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    slug = sorted(PROMOTED_SERVICE_SLUGS)[0]
    db_file = tmp_path / "mois-source.sqlite"

    # 미리 sync된 Phase A 소스 DB를 흉내: provider 스키마 생성 + open 1행.
    setup_engine = create_engine(f"sqlite:///{db_file}")
    mois_db.Base.metadata.create_all(setup_engine)
    with Session(setup_engine) as setup_session:
        setup_session.add(
            mois_db.PlaceMaster(
                service_slug=slug,
                mng_no="MNG-0001",
                place_name="테스트 업소",
                is_open=True,
            )
        )
        # 영업중이 아닌 행은 iter_open_place_records에서 제외되어야 한다.
        setup_session.add(
            mois_db.PlaceMaster(
                service_slug=slug,
                mng_no="MNG-0002",
                place_name="폐업 업소",
                is_open=False,
            )
        )
        setup_session.commit()
    setup_engine.dispose()

    # engine/session lifecycle을 관찰하기 위해 fetcher가 쓰는 심볼을 delegating
    # proxy로 감싼다(실 query는 그대로 real engine/session에 위임).
    disposed: list[bool] = []
    closed: list[bool] = []
    real_create_engine = provider_fetchers.create_engine
    real_session_cls = provider_fetchers.Session

    class _EngineProxy:
        def __init__(self, engine: Any) -> None:
            self._engine = engine

        def dispose(self, *args: Any, **kwargs: Any) -> Any:
            disposed.append(True)
            return self._engine.dispose(*args, **kwargs)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._engine, name)

    class _SessionProxy:
        def __init__(self, session: Any) -> None:
            self._session = session

        def close(self, *args: Any, **kwargs: Any) -> Any:
            closed.append(True)
            return self._session.close(*args, **kwargs)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._session, name)

    def _spy_create_engine(url: str, *args: Any, **kwargs: Any) -> Any:
        return _EngineProxy(real_create_engine(url, *args, **kwargs))

    def _spy_session(engine: Any, *args: Any, **kwargs: Any) -> Any:
        target = engine._engine if isinstance(engine, _EngineProxy) else engine
        return _SessionProxy(real_session_cls(target, *args, **kwargs))

    monkeypatch.setattr(provider_fetchers, "create_engine", _spy_create_engine)
    monkeypatch.setattr(provider_fetchers, "Session", _spy_session)

    settings = KorTravelMapSettings(mois_source_db_path=str(db_file))
    records = list(fetch_mois_license_records(settings))

    assert len(records) == 1
    assert records[0].service_slug == slug
    assert records[0].mng_no == "MNG-0001"
    assert closed == [True]
    assert disposed == [True]


async def _acollect(agen: AsyncIterator[Any]) -> list[Any]:
    out: list[Any] = []
    async for item in agen:
        out.append(item)
    return out


class _FakeKnpsFiles:
    def __init__(self, records: list[object]) -> None:
        self._records = records
        self.place_calls: list[str] = []
        self.geo_calls: list[str] = []

    async def read_place_records(
        self, key: str, **_kwargs: Any
    ) -> tuple[object, ...]:
        self.place_calls.append(key)
        return tuple(self._records)

    async def read_geo_records(self, key: str, **_kwargs: Any) -> tuple[object, ...]:
        self.geo_calls.append(key)
        return tuple(self._records)


class _FakeKnpsClient:
    instances: list[_FakeKnpsClient] = []
    records: list[object] = []

    def __init__(self, **_kwargs: Any) -> None:
        self.closed = False
        self.files = _FakeKnpsFiles(list(type(self).records))
        _FakeKnpsClient.instances.append(self)

    async def aclose(self) -> None:
        self.closed = True


def _install_fake_knps(
    monkeypatch: pytest.MonkeyPatch, *, records: list[object]
) -> type[_FakeKnpsClient]:
    _FakeKnpsClient.instances = []
    _FakeKnpsClient.records = records
    module = ModuleType("knps")
    module.__dict__["KnpsClient"] = _FakeKnpsClient
    monkeypatch.setitem(sys.modules, "knps", module)
    return _FakeKnpsClient


def test_knps_point_records_fetch_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_knps(monkeypatch, records=[object(), object(), object()])
    settings = KorTravelMapSettings(knps_point_dataset_key="knps_visitor_centers")

    records = asyncio.run(_acollect(fetch_knps_point_records(settings)))

    assert len(records) == 3
    assert len(fake.instances) == 1
    client = fake.instances[0]
    assert client.files.place_calls == ["knps_visitor_centers"]
    assert client.closed is True


def test_knps_geometry_records_fetch_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_knps(monkeypatch, records=[object(), object()])
    settings = KorTravelMapSettings(knps_geometry_dataset_key="knps_trails")

    records = asyncio.run(_acollect(fetch_knps_geometry_records(settings)))

    assert len(records) == 2
    client = fake.instances[0]
    assert client.files.geo_calls == ["knps_trails"]
    assert client.closed is True


def test_knps_point_records_fetch_closes_on_partial_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_knps(monkeypatch, records=[object(), object(), object()])
    settings = KorTravelMapSettings(knps_point_dataset_key="knps_visitor_centers")

    async def _take_one_then_close() -> None:
        agen = fetch_knps_point_records(settings)
        first = await agen.__anext__()
        assert first is not None
        # 조기 종료 시에도 finally의 ``aclose()``가 실행되어 client가 닫혀야 한다.
        await agen.aclose()

    asyncio.run(_take_one_then_close())

    assert fake.instances[0].closed is True


class _FakeForestPage:
    def __init__(self, items: list[object]) -> None:
        self.items = tuple(items)


class _FakeForestTravel:
    def __init__(self, forests: list[object], arboretums: list[object]) -> None:
        self._forests = forests
        self._arboretums = arboretums

    async def standard_recreation_forests(
        self, *, page_no: int = 1, num_of_rows: int = 10, **_kwargs: Any
    ) -> _FakeForestPage:
        return _FakeForestPage(self._forests)

    async def recreation_forest_arboretums(
        self, *, name: str | None = None
    ) -> tuple[object, ...]:
        return tuple(self._arboretums)


class _FakeForestClient:
    instances: list[_FakeForestClient] = []
    forests: list[object] = []
    arboretums: list[object] = []

    def __init__(self, *, api_key: str | None = None, **_kwargs: Any) -> None:
        self.api_key = api_key
        self.closed = False
        self.travel = _FakeForestTravel(
            list(type(self).forests), list(type(self).arboretums)
        )
        _FakeForestClient.instances.append(self)

    async def iter_pages(
        self, fetch_page: Any, *, page_no: int = 1, num_of_rows: int = 10, **kwargs: Any
    ) -> AsyncIterator[_FakeForestPage]:
        # 단일 페이지(테스트). 실제 has_next_page 페이지네이션은 provider 책임.
        yield await fetch_page(page_no=page_no, num_of_rows=num_of_rows, **kwargs)

    async def aclose(self) -> None:
        self.closed = True


def _install_fake_krforest(
    monkeypatch: pytest.MonkeyPatch,
    *,
    forests: list[object],
    arboretums: list[object],
) -> type[_FakeForestClient]:
    _FakeForestClient.instances = []
    _FakeForestClient.forests = forests
    _FakeForestClient.arboretums = arboretums
    module = ModuleType("krforest")
    module.__dict__["ForestClient"] = _FakeForestClient
    monkeypatch.setitem(sys.modules, "krforest", module)
    return _FakeForestClient


def test_krforest_recreation_forests_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    agen = fetch_krforest_recreation_forests(settings)
    with pytest.raises(ProviderCredentialMissing):
        asyncio.run(agen.__anext__())


def test_krforest_recreation_forests_fetch_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_krforest(
        monkeypatch, forests=[object(), object()], arboretums=[]
    )
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("forest-key"))

    records = asyncio.run(_acollect(fetch_krforest_recreation_forests(settings)))

    assert len(records) == 2
    client = fake.instances[0]
    assert client.api_key == "forest-key"
    assert client.closed is True


def test_krforest_arboretums_fetch_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_krforest(
        monkeypatch, forests=[], arboretums=[object(), object(), object()]
    )
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("forest-key"))

    records = asyncio.run(_acollect(fetch_krforest_arboretums(settings)))

    assert len(records) == 3
    assert fake.instances[0].closed is True


def test_fetch_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    generator = fetch_datagokr_cultural_festivals(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_fetch_yields_records_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_datagokr(monkeypatch)
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

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
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    generator = fetch_datagokr_cultural_festivals(settings)
    first = next(generator)
    assert first is not None
    generator.close()

    assert fake.instances[0].closed is True


def test_standard_museums_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    generator = fetch_standard_museums(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_standard_museums_fetch_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_datagokr(monkeypatch)
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = list(fetch_standard_museums(settings))

    assert len(records) == 3
    client = fake.instances[0]
    assert client.api_key == "service-key"
    assert client.closed is True


class _FakeFestivalPage:
    def __init__(self, items: list[object]) -> None:
        self.items = tuple(items)


class _FakeVisitKoreaClient:
    instances: list[_FakeVisitKoreaClient] = []
    items: list[object] = []

    def __init__(self, *, service_key: str | None = None, **_kwargs: Any) -> None:
        self.service_key = service_key
        self.closed = False
        self.search_calls: list[Any] = []
        _FakeVisitKoreaClient.instances.append(self)

    def search_festival(
        self, event_start_date: Any, *, page_no: int = 1, num_of_rows: int = 10, **_kw: Any
    ) -> _FakeFestivalPage:
        self.search_calls.append(event_start_date)
        return _FakeFestivalPage(type(self).items)

    def iter_pages(
        self, fetch_page: Any, *args: Any, page_no: int = 1, num_of_rows: int = 10, **kw: Any
    ) -> Iterator[_FakeFestivalPage]:
        yield fetch_page(*args, page_no=page_no, num_of_rows=num_of_rows, **kw)

    def close(self) -> None:
        self.closed = True


def _install_fake_visitkorea(
    monkeypatch: pytest.MonkeyPatch, *, items: list[object]
) -> type[_FakeVisitKoreaClient]:
    _FakeVisitKoreaClient.instances = []
    _FakeVisitKoreaClient.items = items
    module = ModuleType("visitkorea")
    module.__dict__["KrTourApiClient"] = _FakeVisitKoreaClient
    monkeypatch.setitem(sys.modules, "visitkorea", module)
    return _FakeVisitKoreaClient


def test_visitkorea_festival_events_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    generator = fetch_visitkorea_festival_events(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_visitkorea_festival_events_fetch_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_visitkorea(monkeypatch, items=[object(), object()])
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = list(fetch_visitkorea_festival_events(settings))

    assert len(records) == 2
    client = fake.instances[0]
    assert client.service_key == "service-key"
    assert client.closed is True
    # search_festival에 event_start_date(올해 1월 1일)를 넘긴다.
    assert client.search_calls
    assert client.search_calls[0].month == 1


class _FakeBeachPage:
    def __init__(self, items: list[object]) -> None:
        self.items = tuple(items)


class _FakeKhoaClient:
    instances: list[_FakeKhoaClient] = []
    per_sido: list[object] = []

    def __init__(self, *, api_key: str | None = None, **_kwargs: Any) -> None:
        self.api_key = api_key
        self.closed = False
        self.calls: list[str] = []
        _FakeKhoaClient.instances.append(self)

    def oceans_beach_info(
        self, sido_nm: str, *, page_no: int = 1, num_of_rows: int = 100, **_kw: Any
    ) -> _FakeBeachPage:
        self.calls.append(sido_nm)
        # 단일 페이지(short)만 반환 → 페이지네이션 stop.
        return _FakeBeachPage(list(type(self).per_sido) if page_no == 1 else [])

    def close(self) -> None:
        self.closed = True


def _install_fake_khoa(
    monkeypatch: pytest.MonkeyPatch, *, sidos: tuple[str, ...], per_sido: list[object]
) -> type[_FakeKhoaClient]:
    _FakeKhoaClient.instances = []
    _FakeKhoaClient.per_sido = per_sido
    module = ModuleType("khoa")
    module.__dict__["KhoaClient"] = _FakeKhoaClient
    module.__dict__["OCEANS_BEACH_INFO_DEFAULT_SIDO_NAMES"] = sidos
    monkeypatch.setitem(sys.modules, "khoa", module)
    return _FakeKhoaClient


def test_khoa_beaches_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    generator = fetch_khoa_beaches(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_khoa_beaches_fetch_iterates_sido_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_khoa(
        monkeypatch, sidos=("부산광역시", "강원특별자치도"), per_sido=[object(), object()]
    )
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = list(fetch_khoa_beaches(settings))

    # 2 sido × 2 record = 4.
    assert len(records) == 4
    client = fake.instances[0]
    assert client.calls == ["부산광역시", "강원특별자치도"]
    assert client.closed is True


class _FakeKrairportClient:
    instances: list[_FakeKrairportClient] = []
    airports_data: list[object] = []

    def __init__(
        self,
        *,
        kac_service_key: str | None = None,
        iiac_service_key: str | None = None,
        **_kwargs: Any,
    ) -> None:
        self.kac_service_key = kac_service_key
        self.iiac_service_key = iiac_service_key
        self.closed = False
        self.active_calls: list[bool] = []
        _FakeKrairportClient.instances.append(self)

    def airports(self, *, active: bool = True) -> list[object]:
        self.active_calls.append(active)
        return list(type(self).airports_data)

    def close(self) -> None:
        self.closed = True


def _install_fake_krairport(
    monkeypatch: pytest.MonkeyPatch, *, airports: list[object]
) -> type[_FakeKrairportClient]:
    _FakeKrairportClient.instances = []
    _FakeKrairportClient.airports_data = airports
    module = ModuleType("krairport")
    module.__dict__["KrairportClient"] = _FakeKrairportClient
    monkeypatch.setitem(sys.modules, "krairport", module)
    return _FakeKrairportClient


def test_krairport_airports_fetch_yields_and_closes_keyless(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # keyless: credential 없이도 번들 정적 메타데이터를 yield 해야 한다.
    fake = _install_fake_krairport(
        monkeypatch, airports=[object(), object(), object()]
    )
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    records = list(fetch_krairport_airports(settings))

    assert len(records) == 3
    assert len(fake.instances) == 1
    client = fake.instances[0]
    assert client.kac_service_key is None
    assert client.iiac_service_key is None
    assert client.active_calls == [True]
    assert client.closed is True


def test_krairport_airports_fetch_passes_key_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_krairport(monkeypatch, airports=[object()])
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("airport-key"))

    records = list(fetch_krairport_airports(settings))

    assert len(records) == 1
    client = fake.instances[0]
    assert client.kac_service_key == "airport-key"
    assert client.iiac_service_key == "airport-key"
    assert client.closed is True


def test_krairport_airports_fetch_closes_on_partial_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_krairport(
        monkeypatch, airports=[object(), object(), object()]
    )
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    generator = fetch_krairport_airports(settings)
    first = next(generator)
    assert first is not None
    generator.close()

    assert fake.instances[0].closed is True


class _FakeAirKoreaClient:
    instances: list[_FakeAirKoreaClient] = []
    stations_total: int = 0
    per_sido: list[object] = []

    def __init__(self, *, service_key: str | None = None, **_kwargs: Any) -> None:
        self.service_key = service_key
        self.closed = False
        self.station_calls: list[int] = []
        self.sido_calls: list[str] = []
        _FakeAirKoreaClient.instances.append(self)

    def stations(
        self, *, page_no: int = 1, num_of_rows: int = 100, **_kw: Any
    ) -> list[object]:
        self.station_calls.append(page_no)
        start = (page_no - 1) * num_of_rows
        end = min(start + num_of_rows, type(self).stations_total)
        return [object() for _ in range(max(0, end - start))]

    def sido_measurements(
        self, sido_name: str, *, page_no: int = 1, num_of_rows: int = 100, **_kw: Any
    ) -> list[object]:
        self.sido_calls.append(sido_name)
        # 시도별 단일 페이지(short)만 반환 → 페이지네이션 stop.
        return list(type(self).per_sido) if page_no == 1 else []

    def close(self) -> None:
        self.closed = True


def _install_fake_airkorea(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stations_total: int = 0,
    per_sido: list[object] | None = None,
) -> type[_FakeAirKoreaClient]:
    _FakeAirKoreaClient.instances = []
    _FakeAirKoreaClient.stations_total = stations_total
    _FakeAirKoreaClient.per_sido = per_sido or []
    module = ModuleType("airkorea")
    module.__dict__["AirKoreaClient"] = _FakeAirKoreaClient
    monkeypatch.setitem(sys.modules, "airkorea", module)
    return _FakeAirKoreaClient


def test_airkorea_stations_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    generator = fetch_airkorea_stations(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_airkorea_stations_paginates_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # total 103 → page1=100(full)·page2=3(short) → 2 pages, short-page stop.
    fake = _install_fake_airkorea(monkeypatch, stations_total=103)
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("svc"))

    records = list(fetch_airkorea_stations(settings))

    assert len(records) == 103
    client = fake.instances[0]
    assert client.service_key == "svc"
    assert client.station_calls == [1, 2]
    assert client.closed is True


def test_airkorea_air_quality_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    generator = fetch_airkorea_air_quality(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_airkorea_air_quality_iterates_all_sido_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_airkorea(
        monkeypatch, per_sido=[object(), object()]
    )
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("svc"))

    records = list(fetch_airkorea_air_quality(settings))

    # 17 시도 × 2 record = 34.
    assert len(records) == 34
    client = fake.instances[0]
    assert len(client.sido_calls) == 17
    assert client.sido_calls[0] == "서울"
    assert client.closed is True


class _FakeStation:
    def __init__(self, uni_id: str, product_code: str | None = None) -> None:
        self.uni_id = uni_id
        self.product_code = product_code


class _FakeOpinetArea:
    def __init__(self, code: str) -> None:
        self.code = code


class _FakeOpinetClient:
    instances: list[_FakeOpinetClient] = []
    stations: list[object] = []
    details: dict[str, object] = {}
    root_areas: list[_FakeOpinetArea] = []
    child_areas: dict[str, list[_FakeOpinetArea]] = {}
    low_top: dict[tuple[str, str], list[object]] = {}
    around: dict[tuple[float, float, str], list[object]] = {}

    def __init__(self, *, api_key: str | None = None, **_kwargs: Any) -> None:
        self.api_key = api_key
        self.closed = False
        self.bbox_calls: list[tuple[float, float, float, float, int]] = []
        self.detail_calls: list[str] = []
        self.area_calls: list[str | None] = []
        self.low_top_calls: list[tuple[str, int, str | None]] = []
        self.around_calls: list[tuple[float, float, int, str]] = []
        _FakeOpinetClient.instances.append(self)

    def iter_stations_in_bbox(
        self,
        *,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        radius_m: int = 5000,
        **_kw: Any,
    ) -> Iterator[object]:
        self.bbox_calls.append((min_lon, min_lat, max_lon, max_lat, radius_m))
        yield from type(self).stations

    def get_station_detail(self, uni_id: str) -> object:
        self.detail_calls.append(uni_id)
        return type(self).details.get(uni_id, object())

    def get_area_codes(self, sido: str | None = None) -> list[_FakeOpinetArea]:
        self.area_calls.append(sido)
        if sido is None:
            return list(type(self).root_areas)
        return list(type(self).child_areas.get(sido, []))

    def get_lowest_price_top20(
        self, prodcd: str, cnt: int = 10, area: str | None = None
    ) -> list[object]:
        self.low_top_calls.append((prodcd, cnt, area))
        return list(type(self).low_top.get((area or "", prodcd), []))

    def search_stations_around(
        self,
        *,
        lon: float,
        lat: float,
        radius_m: int = 5000,
        prodcd: str,
        **_kw: Any,
    ) -> list[object]:
        self.around_calls.append((lon, lat, radius_m, prodcd))
        return list(type(self).around.get((lon, lat, prodcd), []))

    def close(self) -> None:
        self.closed = True


def _install_fake_opinet(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stations: list[object],
    details: dict[str, object] | None = None,
    root_areas: list[_FakeOpinetArea] | None = None,
    child_areas: dict[str, list[_FakeOpinetArea]] | None = None,
    low_top: dict[tuple[str, str], list[object]] | None = None,
    around: dict[tuple[float, float, str], list[object]] | None = None,
) -> type[_FakeOpinetClient]:
    _FakeOpinetClient.instances = []
    _FakeOpinetClient.stations = stations
    _FakeOpinetClient.details = details or {}
    _FakeOpinetClient.root_areas = root_areas or []
    _FakeOpinetClient.child_areas = child_areas or {}
    _FakeOpinetClient.low_top = low_top or {}
    _FakeOpinetClient.around = around or {}
    module = ModuleType("opinet")
    module.__dict__["OpinetClient"] = _FakeOpinetClient
    monkeypatch.setitem(sys.modules, "opinet", module)
    return _FakeOpinetClient


def test_opinet_stations_disabled_raises() -> None:
    settings = KorTravelMapSettings(
        opinet_api_key=SecretStr("k"), opinet_scope_mode="disabled"
    )
    with pytest.raises(ProviderCredentialMissing, match="disabled"):
        next(fetch_opinet_stations(settings))


def test_opinet_stations_missing_key_raises() -> None:
    settings = KorTravelMapSettings(
        opinet_api_key=None, opinet_scope_mode="bbox",
        opinet_scope_bbox="126.0,37.0,127.0,38.0",
    )
    with pytest.raises(ProviderCredentialMissing, match="OPINET_API_KEY"):
        next(fetch_opinet_stations(settings))


def test_center_radius_to_bbox_math() -> None:
    from kortravelmap.dagster.provider_fetchers import _center_radius_to_bbox

    min_lon, min_lat, max_lon, max_lat = _center_radius_to_bbox(127.0, 37.5, 5.0)
    # 대칭 + 위경도 폭(위도 5km≈0.045°, 경도는 cos(37.5)로 더 넓음).
    assert min_lon < 127.0 < max_lon
    assert min_lat < 37.5 < max_lat
    assert abs((37.5 - min_lat) - 5.0 / 111.0) < 1e-6
    assert (max_lon - 127.0) > (max_lat - 37.5)  # 경도 폭 > 위도 폭


def test_opinet_stations_poi_mode_enumerates_and_dedups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_opinet(
        monkeypatch, stations=[_FakeStation("P1"), _FakeStation("P2")]
    )
    monkeypatch.setattr(
        provider_fetchers,
        "_opinet_poi_target_bboxes",
        lambda _settings: [
            (126.9, 37.4, 127.1, 37.6),
            (129.0, 35.1, 129.3, 35.3),
        ],
    )
    settings = KorTravelMapSettings(
        opinet_api_key=SecretStr("k"), opinet_scope_mode="poi_cache_target"
    )

    records = list(fetch_opinet_stations(settings))

    # 2 target bbox 각각 동일 2 station 반환 → uni_id dedup → P1, P2.
    assert [r.uni_id for r in records] == ["P1", "P2"]
    client = fake.instances[0]
    assert len(client.bbox_calls) == 2
    assert client.closed is True


def test_opinet_stations_poi_mode_empty_targets_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        provider_fetchers, "_opinet_poi_target_bboxes", lambda _settings: []
    )
    settings = KorTravelMapSettings(
        opinet_api_key=SecretStr("k"), opinet_scope_mode="poi_cache_target"
    )
    with pytest.raises(ProviderCredentialMissing, match="활성 target"):
        next(fetch_opinet_stations(settings))


def test_opinet_stations_bbox_missing_raises() -> None:
    settings = KorTravelMapSettings(
        opinet_api_key=SecretStr("k"), opinet_scope_mode="bbox", opinet_scope_bbox=None
    )
    with pytest.raises(ProviderCredentialMissing, match="OPINET_SCOPE_BBOX"):
        next(fetch_opinet_stations(settings))


def test_opinet_stations_bbox_invalid_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_opinet(monkeypatch, stations=[])
    settings = KorTravelMapSettings(
        opinet_api_key=SecretStr("k"), opinet_scope_mode="bbox",
        opinet_scope_bbox="126.0,37.0,127.0",  # 3개만
    )
    with pytest.raises(ProviderCredentialMissing, match="4개 값"):
        next(fetch_opinet_stations(settings))


def test_opinet_stations_bbox_enumerates_dedups_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_opinet(
        monkeypatch,
        stations=[_FakeStation("A1"), _FakeStation("A2"), _FakeStation("A1")],
    )
    settings = KorTravelMapSettings(
        opinet_api_key=SecretStr("certkey"), opinet_scope_mode="bbox",
        opinet_scope_bbox="126.0,37.0,127.0,38.0", opinet_scope_radius_m=3000,
    )

    records = list(fetch_opinet_stations(settings))

    # uni_id dedup → A1, A2.
    assert [r.uni_id for r in records] == ["A1", "A2"]
    client = fake.instances[0]
    assert client.api_key == "certkey"
    assert client.bbox_calls == [(126.0, 37.0, 127.0, 38.0, 3000)]
    assert client.closed is True


def test_opinet_stations_low_top_area_dedups_by_station(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_opinet(
        monkeypatch,
        stations=[],
        root_areas=[_FakeOpinetArea("01")],
        child_areas={"01": [_FakeOpinetArea("0101"), _FakeOpinetArea("0102")]},
        low_top={
            ("0101", "B027"): [_FakeStation("A1", "B027")],
            ("0101", "D047"): [_FakeStation("A1", "D047")],
            ("0102", "B034"): [_FakeStation("A2", "B034")],
        },
    )
    settings = KorTravelMapSettings(
        opinet_api_key=SecretStr("certkey"), opinet_scope_mode="low_top_area"
    )

    records = list(fetch_opinet_stations(settings))

    assert [r.uni_id for r in records] == ["A1", "A2"]
    client = fake.instances[0]
    assert client.area_calls == [None, "01"]
    assert client.low_top_calls == [
        ("B027", 20, "0101"),
        ("D047", 20, "0101"),
        ("B034", 20, "0101"),
        ("B027", 20, "0102"),
        ("D047", 20, "0102"),
        ("B034", 20, "0102"),
    ]
    assert client.closed is True


def test_opinet_stations_low_top_area_falls_back_to_sample_grid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_opinet(
        monkeypatch,
        stations=[],
        root_areas=[],
        around={
            (127.0, 37.5, "B027"): [_FakeStation("A1", "B027")],
            (127.0, 37.5, "D047"): [_FakeStation("A1", "D047")],
            (129.0, 35.2, "B034"): [_FakeStation("A2", "B034")],
        },
    )
    monkeypatch.setattr(
        provider_fetchers,
        "_opinet_sample_grid_centers",
        lambda: iter([(127.0, 37.5), (129.0, 35.2)]),
    )
    settings = KorTravelMapSettings(
        opinet_api_key=SecretStr("certkey"), opinet_scope_mode="low_top_area"
    )

    records = list(fetch_opinet_stations(settings))

    assert [r.uni_id for r in records] == ["A1", "A2"]
    client = fake.instances[0]
    assert client.area_calls == [None]
    assert client.low_top_calls == []
    assert client.around_calls == [
        (127.0, 37.5, 5000, "B027"),
        (127.0, 37.5, 5000, "D047"),
        (127.0, 37.5, 5000, "B034"),
        (129.0, 35.2, 5000, "B027"),
        (129.0, 35.2, 5000, "D047"),
        (129.0, 35.2, 5000, "B034"),
    ]
    assert client.closed is True


def test_opinet_station_price_details_missing_key_raises() -> None:
    settings = KorTravelMapSettings(
        opinet_api_key=None,
        opinet_scope_mode="bbox",
        opinet_scope_bbox="126.0,37.0,127.0,38.0",
    )
    with pytest.raises(ProviderCredentialMissing, match="OPINET_API_KEY"):
        next(fetch_opinet_station_price_details(settings))


def test_opinet_station_price_details_fetches_detail_for_deduped_stations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d1 = object()
    d2 = object()
    fake = _install_fake_opinet(
        monkeypatch,
        stations=[_FakeStation("A1"), _FakeStation("A2"), _FakeStation("A1")],
        details={"A1": d1, "A2": d2},
    )
    settings = KorTravelMapSettings(
        opinet_api_key=SecretStr("certkey"),
        opinet_scope_mode="bbox",
        opinet_scope_bbox="126.0,37.0,127.0,38.0",
        opinet_scope_radius_m=3000,
    )

    records = list(fetch_opinet_station_price_details(settings))

    assert records == [d1, d2]
    client = fake.instances[0]
    assert client.detail_calls == ["A1", "A2"]
    assert client.closed is True


def test_opinet_station_price_details_low_top_area_dedups_by_station_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_opinet(
        monkeypatch,
        stations=[],
        root_areas=[_FakeOpinetArea("01")],
        child_areas={"01": [_FakeOpinetArea("0101")]},
        low_top={
            ("0101", "B027"): [_FakeStation("A1", "B027")],
            ("0101", "D047"): [_FakeStation("A1", "D047")],
            ("0101", "B034"): [_FakeStation("A2", "B034")],
        },
    )
    settings = KorTravelMapSettings(
        opinet_api_key=SecretStr("certkey"), opinet_scope_mode="low_top_area"
    )

    records = list(fetch_opinet_station_price_details(settings))

    assert [(r.uni_id, r.product_code) for r in records] == [
        ("A1", "B027"),
        ("A1", "D047"),
        ("A2", "B034"),
    ]
    client = fake.instances[0]
    assert client.detail_calls == []
    assert client.low_top_calls == [
        ("B027", 20, "0101"),
        ("D047", 20, "0101"),
        ("B034", 20, "0101"),
    ]
    assert client.closed is True


def test_opinet_station_price_details_low_top_area_falls_back_to_sample_grid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_opinet(
        monkeypatch,
        stations=[],
        root_areas=[_FakeOpinetArea("01")],
        child_areas={"01": [_FakeOpinetArea("0101")]},
        low_top={},
        around={
            (127.0, 37.5, "B027"): [_FakeStation("A1", "B027")],
            (127.0, 37.5, "D047"): [_FakeStation("A1", "D047")],
            (127.0, 37.5, "B034"): [_FakeStation("A2", "B034")],
        },
    )
    monkeypatch.setattr(
        provider_fetchers,
        "_opinet_sample_grid_centers",
        lambda: iter([(127.0, 37.5)]),
    )
    settings = KorTravelMapSettings(
        opinet_api_key=SecretStr("certkey"), opinet_scope_mode="low_top_area"
    )

    records = list(fetch_opinet_station_price_details(settings))

    assert [(r.uni_id, r.product_code) for r in records] == [
        ("A1", "B027"),
        ("A1", "D047"),
        ("A2", "B034"),
    ]
    client = fake.instances[0]
    assert client.detail_calls == []
    assert client.low_top_calls == [
        ("B027", 20, "0101"),
        ("D047", 20, "0101"),
        ("B034", 20, "0101"),
    ]
    assert client.around_calls == [
        (127.0, 37.5, 5000, "B027"),
        (127.0, 37.5, 5000, "D047"),
        (127.0, 37.5, 5000, "B034"),
    ]
    assert client.closed is True


def test_standard_tourist_attractions_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    generator = fetch_standard_tourist_attractions(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_standard_tourist_attractions_fetch_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_datagokr(monkeypatch)
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = list(fetch_standard_tourist_attractions(settings))

    assert len(records) == 2
    assert fake.instances[0].closed is True


def test_standard_parking_lots_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    generator = fetch_standard_parking_lots(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_standard_parking_lots_fetch_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_datagokr(monkeypatch)
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = list(fetch_standard_parking_lots(settings))

    assert len(records) == 4
    assert fake.instances[0].closed is True


def test_krheritage_fetch_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    generator = fetch_krheritage_events(settings)
    with pytest.raises(ProviderCredentialMissing):
        next(generator)


def test_krheritage_fetch_yields_records_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_krheritage(monkeypatch)
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = list(fetch_krheritage_events(settings))

    assert len(records) == 2
    assert len(fake.instances) == 1
    client = fake.instances[0]
    assert client.api_key == "service-key"
    assert client.closed is True


def test_krheritage_items_fetch_is_keyless_iterates_kind_codes_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # khs.go.kr search/detail은 keyless (#380) — credential 없이도 fetch.
    fake = _install_fake_krheritage(
        monkeypatch,
        details_by_kind={"11": [object()], "13": [object(), object()]},
    )
    settings = KorTravelMapSettings(
        data_go_kr_service_key=None,
        krheritage_kind_codes="11, 13",
    )

    records = list(fetch_krheritage_items(settings))

    assert len(records) == 3
    assert len(fake.instances) == 1
    client = fake.instances[0]
    assert client.api_key is None
    assert client.closed is True
    # 종목코드별 iter_all_details(page_size=100, ccba_kdcd=...) 1회씩.
    assert client.search.calls == [(100, "11"), (100, "13")]


def test_krheritage_items_fetch_stops_at_max_items_per_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_krheritage(
        monkeypatch,
        details_by_kind={
            "11": [object(), object(), object()],
            "12": [object()],
        },
    )
    settings = KorTravelMapSettings(
        krheritage_kind_codes="11,12",
        krheritage_max_items_per_run=2,
    )

    records = list(fetch_krheritage_items(settings))

    # detail 1콜/건 보호 — 상한 2에서 중단, 두 번째 종목코드(12)는 미호출.
    assert len(records) == 2
    client = fake.instances[0]
    assert client.closed is True
    assert client.search.calls == [(100, "11")]


def test_live_resource_returns_iterable_when_credentials_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY", "service-key")
    sentinel = [object(), object()]

    def _fake_fetch(_settings: KorTravelMapSettings) -> Iterable[Any]:
        return sentinel

    resource_def = build_provider_record_live_resource(_DATAGOKR_SPEC, _fake_fetch)
    resource_fn = cast("Callable[[object], object]", resource_def.resource_fn)

    result = resource_fn(build_init_resource_context())

    assert result is sentinel


def test_live_resource_wraps_sync_generator_for_dagster_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY", "service-key")
    sentinel = [object(), object()]

    def _fake_fetch(_settings: KorTravelMapSettings) -> Iterator[Any]:
        yield from sentinel

    resource_def = build_provider_record_live_resource(_DATAGOKR_SPEC, _fake_fetch)
    resource_fn = cast("Callable[[object], object]", resource_def.resource_fn)

    result = resource_fn(build_init_resource_context())

    assert isinstance(result, Iterable)
    assert not isinstance(result, Iterator)
    assert list(cast(Iterable[Any], result)) == sentinel


def test_live_resource_raises_guard_message_when_credentials_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY", raising=False)

    def _fake_fetch(_settings: KorTravelMapSettings) -> Iterable[Any]:  # pragma: no cover
        raise AssertionError("fetch must not run when credentials are missing")

    resource_def = build_provider_record_live_resource(_DATAGOKR_SPEC, _fake_fetch)
    resource_fn = cast("Callable[[object], object]", resource_def.resource_fn)

    with pytest.raises(RuntimeError) as exc_info:
        resource_fn(build_init_resource_context())

    message = str(exc_info.value)
    assert "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY" in message
    assert "credential" in message


def test_datagokr_resource_definition_is_live_not_guard() -> None:
    live = PROVIDER_RECORD_RESOURCE_DEFINITIONS["datagokr_cultural_festivals"]
    guard = build_provider_record_guard_resource(_DATAGOKR_SPEC)

    assert live.description is not None
    assert "live fetcher" in live.description
    assert "live fetcher" not in (guard.description or "")
    # krheritage_items도 live로 wiring 완료 (#380) — guard 아님.
    heritage_items = PROVIDER_RECORD_RESOURCE_DEFINITIONS["krheritage_items"]
    assert "live fetcher" in (heritage_items.description or "")
