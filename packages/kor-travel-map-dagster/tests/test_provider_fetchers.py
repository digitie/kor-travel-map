"""Provider public client live fetcher + live resource 단위 테스트 (T-RV-04b)."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

import kortravelmap.dagster.provider_fetchers as provider_fetchers
from kortravelmap.dagster.feature_operation_tracking import (
    FeatureOperationExecutionGuard,
)
from kortravelmap.dagster.provider_fetchers import (
    ProviderCredentialMissing,
    fetch_datagokr_cultural_festivals,
    fetch_khoa_beaches,
    fetch_knps_geometry_records,
    fetch_knps_point_records,
    fetch_kor_travel_concierge_youtube_features,
    fetch_krforest_arboretums,
    fetch_krforest_recreation_forests,
    fetch_krheritage_events,
    fetch_krheritage_items,
    fetch_mois_license_records,
    fetch_standard_museums,
    fetch_standard_parking_lots,
    fetch_standard_tourist_attractions,
    fetch_visitkorea_festival_events,
)
from kortravelmap.dagster.provider_pagination import (
    ProviderPaginationOverrun,
    ProviderPaginationStalled,
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

_PANEL_CLIENT = object()
_PANEL_INSTANCE = object()
_PANEL_RUN_ID = "panel-test"
_PANEL_GUARD = FeatureOperationExecutionGuard(
    client=cast(Any, _PANEL_CLIENT),
    instance=_PANEL_INSTANCE,
    operation_key=None,
    memberships=(),
    dagster_run_id=_PANEL_RUN_ID,
    trigger_kind=None,
)


def _guarded_init_resource_context() -> Any:
    return SimpleNamespace(
        resource_config={},
        resources=SimpleNamespace(
            feature_operation_guard=_PANEL_GUARD,
            kor_travel_map_client=_PANEL_CLIENT,
        ),
        instance=_PANEL_INSTANCE,
        run=SimpleNamespace(job_name="panel_only_job", run_id=_PANEL_RUN_ID),
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


class _FakeStandardPage:
    """datagokr ``StandardPage``의 종료 판정에 필요한 최소 표면."""

    def __init__(self, items: list[object], total_count: int) -> None:
        self.items = items
        self.total_count = total_count


class _FakeStandardService:
    """datagokr 표준데이터 service — **``list`` 페이지 표면**을 흉내낸다.

    Map은 provider의 ``iter_all()``을 더 이상 쓰지 않는다. 그 구현이 짧은 페이지를
    무조건 마지막 페이지로 읽는데(`b8f1254`), 같은 릴리스의 행 단위
    ``except ValidationError: continue``와 겹치면 기형 행 하나가 목록을 조용히
    끊기 때문이다. Map은 ``total_count``가 권위인 자기 페이지네이터로 옮겼고,
    fake도 그 표면을 들어야 그 변화를 잴 수 있다.
    """

    def __init__(self, records: list[object]) -> None:
        self._records = records
        self.pages: list[int] = []

    async def list(
        self, *, page_no: int = 1, num_of_rows: int = 1000, **_filters: Any
    ) -> _FakeStandardPage:
        self.pages.append(page_no)
        start = (page_no - 1) * num_of_rows
        return _FakeStandardPage(
            list(self._records[start : start + num_of_rows]), len(self._records)
        )


#: 이름은 유지한다 — 호출부(테스트)가 그대로 읽히게.
_FakeFestivalService = _FakeStandardService
_FakeMuseumArtService = _FakeStandardService


class _FakeDataGoKrClient:
    instances: list[_FakeDataGoKrClient] = []

    def __init__(self, *, api_key: str | None = None, **_kwargs: Any) -> None:
        self.api_key = api_key
        self.closed = False
        self.festival = _FakeFestivalService([object(), object()])
        self.museum_art = _FakeMuseumArtService([object(), object(), object()])
        self.tourist_attraction = _FakeMuseumArtService([object(), object()])
        self.parking = _FakeMuseumArtService([object(), object(), object(), object()])
        self.special_street = _FakeStandardService([object(), object()])
        _FakeDataGoKrClient.instances.append(self)

    async def aclose(self) -> None:
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
        kor_travel_concierge_api_key=SecretStr("concierge-read-key"),
    )

    records = [
        item async for item in fetch_kor_travel_concierge_youtube_features(settings)
    ]

    assert records == [{"id": 1}, {"id": 2}]
    assert len(fake.instances) == 1
    client = fake.instances[0]
    assert client.base_url == "https://kor-travel-concierge.example"
    assert client.headers == {"X-API-Key": "concierge-read-key"}
    assert client.closed is True
    # 기본 endpoint는 ``changes`` — cursor 없이 시작하면 후보당 1행 ledger 전체
    # (upsert/reject/tombstone)를 재생해 철회 전파까지 포함한 full sync가 된다.
    # ``snapshot``은 active upsert만 반환해 reject/tombstone이 영구 미전파된다.
    assert client.calls == [
        ("/api/v1/features/changes", {"limit": 200}),
        ("/api/v1/features/changes", {"limit": 200, "cursor": "c2"}),
    ]


async def test_kor_travel_concierge_youtube_fetch_snapshot_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``snapshot``은 opt-in — 철회 전파가 필요 없는 일회성 초기 적재 검증용."""
    fake = _install_fake_kor_travel_concierge_httpx(
        monkeypatch,
        [{"items": [], "next_cursor": None, "has_more": False}],
    )
    settings = KorTravelMapSettings(
        kor_travel_concierge_base_url="https://kor-travel-concierge.example",
        kor_travel_concierge_api_key=SecretStr("concierge-read-key"),
        kor_travel_concierge_feature_sync_endpoint="snapshot",
    )

    _ = [item async for item in fetch_kor_travel_concierge_youtube_features(settings)]

    assert fake.instances[0].calls == [
        ("/api/v1/features/snapshot", {"limit": 200}),
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


async def test_kor_travel_concierge_youtube_fetch_requires_api_key() -> None:
    generator = fetch_kor_travel_concierge_youtube_features(
        KorTravelMapSettings(
            kor_travel_concierge_base_url="https://kor-travel-concierge.example",
            kor_travel_concierge_api_key=None,
        )
    )

    with pytest.raises(ProviderCredentialMissing, match="DB read scope 키"):
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
    """``by_month`` 표면을 흉내낸다.

    Map은 provider의 ``iter_months()``를 더 이상 쓰지 않는다. 그 안에서 달을 돌면
    이 층이 요청 수를 셀 수 없는데, 비어 있는 달도 요청 1건을 쓰므로 record 수로는
    역산되지 않는다. Map이 창을 소유하고 달마다 부르므로, fake도 그 표면을 들어야
    "달마다 한 번 세는가"를 잴 수 있다.

    이 fake는 첫 달에 record를 전부 주고 나머지 달은 비운다 — 요청 수와 record
    수가 다르다는 사실 자체가 이 변경의 이유이기 때문이다.
    """

    def __init__(self, records: list[object]) -> None:
        self._records = records
        self.calls: list[tuple[int, int]] = []

    # 실물: ``krheritage/services/event.py:21``의 ``async def by_month``.
    async def by_month(self, *, year: int, month: int) -> tuple[object, ...]:
        self.calls.append((year, month))
        if len(self.calls) == 1:
            return tuple(self._records)
        return ()


class _FakeHeritageKey:
    def __init__(self, kind_code: str, index: int) -> None:
        self.ccba_kdcd = kind_code
        self.ccba_asno = f"{index:04d}"
        self.ccba_ctcd = "11"


class _FakeHeritageSummary:
    def __init__(self, kind_code: str, index: int) -> None:
        self.key = _FakeHeritageKey(kind_code, index)
        self.name_ko = f"{kind_code}-{index}"


class _FakeHeritagePage:
    def __init__(self, items: list[object], total: int) -> None:
        self.items = items
        self.total = total


class _FakeHeritageSearchService:
    """국가유산 검색 service — **``list`` + ``details``** 표면을 흉내낸다.

    Map은 provider의 ``iter_all_details()``를 더 이상 쓰지 않는다. 그 안의
    ``iter_pages``가 ``if len(result.items) < page_size: return`` 하나로 끝내는데,
    같은 provider가 복합키 결측 row를 건너뛰므로 둘이 겹치면 목록이 조용히
    끊긴다. Map은 ``PaginatedResult.total``이 권위인 자기 페이지네이터로 옮겼고,
    fake도 그 표면을 들어야 그 변화를 잴 수 있다.
    """

    def __init__(self, details_by_kind: dict[str, list[object]]) -> None:
        self._details_by_kind = details_by_kind
        self.calls: list[tuple[int, str]] = []

    # 실물: ``krheritage/services/search.py:29``의 ``async def list``
    # (keyword-only ``page_size``/``page``/``ccba_*``).
    async def list(
        self, *, page_size: int = 100, page: int = 1, **filters: Any
    ) -> _FakeHeritagePage:
        kind_code = str(filters.get("ccba_kdcd", ""))
        if page == 1:
            self.calls.append((page_size, kind_code))
        details = self._details_by_kind.get(kind_code, [])
        start = (page - 1) * page_size
        window = details[start : start + page_size]
        summaries = [
            _FakeHeritageSummary(kind_code, start + offset)
            for offset in range(len(window))
        ]
        return _FakeHeritagePage(list(summaries), len(details))

    # 실물: ``krheritage/services/search.py:70``의 ``async def details``
    # (``ccba_*`` 3개 위치인자).
    async def details(self, ccba_kdcd: str, ccba_asno: str, ccba_ctcd: str) -> object:
        del ccba_ctcd
        return self._details_by_kind[ccba_kdcd][int(ccba_asno)]


class _FakeHeritageClient:
    instances: list[_FakeHeritageClient] = []
    details_by_kind: dict[str, list[object]] = {}

    def __init__(self, *, api_key: str | None = None, **_kwargs: Any) -> None:
        self.api_key = api_key
        self.closed = False
        self.event = _FakeEventService([object(), object()])
        self.search = _FakeHeritageSearchService(type(self).details_by_kind)
        _FakeHeritageClient.instances.append(self)

    # 실물 ``HeritageClient``에 sync ``close``는 없다 — ``aclose``뿐이다
    # (``krheritage/client.py:80``). fetcher의 ``finally``가 부르는 이름과
    # 같아야 "닫혔다"는 단언이 뜻을 갖는다.
    async def aclose(self) -> None:
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


class _FakeForestNoDataError(Exception):
    """``krforest.ForestNoDataError``의 대역 — 실물은 "더 없음"을 예외로 알린다."""


class _FakeForestPage:
    """실물 ``krforest.models.Page``의 필드 계약을 흉내낸다.

    ``total_count``가 없으면 저장소 페이지네이션 헬퍼가 선언 건수로 상한을 유도하지
    못한다. 종전 대역에는 그 필드가 없었고, 그래서 **페이지네이션이 한 번도
    시험되지 않았다** — 라이브러리 ``iter_pages``의 10,000페이지 fallback이
    아무에게도 보이지 않은 이유다.
    """

    def __init__(self, items: list[object], *, total_count: int | None = None) -> None:
        self.items = tuple(items)
        self.total_count = len(items) if total_count is None else total_count


class _FakeForestTravel:
    def __init__(
        self,
        forests: list[object],
        arboretums: list[object],
        *,
        declared_total: int | None = None,
        page_size_override: int | None = None,
    ) -> None:
        self._forests = forests
        self._arboretums = arboretums
        self._declared_total = declared_total
        self._page_size_override = page_size_override
        self.page_calls: list[int] = []

    async def standard_recreation_forests(
        self, *, page_no: int = 1, num_of_rows: int = 10, **_kwargs: Any
    ) -> _FakeForestPage:
        self.page_calls.append(page_no)
        size = self._page_size_override or num_of_rows
        start = (page_no - 1) * size
        window = self._forests[start : start + size]
        if not window and self._declared_total is None:
            raise _FakeForestNoDataError("no data")
        return _FakeForestPage(
            window,
            total_count=(
                len(self._forests)
                if self._declared_total is None
                else self._declared_total
            ),
        )

    async def recreation_forest_arboretums(
        self, *, name: str | None = None
    ) -> tuple[object, ...]:
        return tuple(self._arboretums)


class _FakeForestClient:
    """대역에 ``iter_pages``가 **없다**.

    프로덕션 코드가 라이브러리 iterator로 되돌아가면 여기서 ``AttributeError``로
    빨개진다. 그것이 의도다 — 라이브러리 iterator는 ``max_pages``를 주지 않으면
    상한을 ``total_count``에서 유도하고, 그 유도가 실패하면 10,000페이지까지 간다.
    """

    instances: list[_FakeForestClient] = []
    forests: list[object] = []
    arboretums: list[object] = []
    declared_total: int | None = None
    page_size_override: int | None = None

    def __init__(self, *, api_key: str | None = None, **_kwargs: Any) -> None:
        self.api_key = api_key
        self.closed = False
        self.travel = _FakeForestTravel(
            list(type(self).forests),
            list(type(self).arboretums),
            declared_total=type(self).declared_total,
            page_size_override=type(self).page_size_override,
        )
        _FakeForestClient.instances.append(self)

    async def aclose(self) -> None:
        self.closed = True


def _install_fake_krforest(
    monkeypatch: pytest.MonkeyPatch,
    *,
    forests: list[object],
    arboretums: list[object],
    declared_total: int | None = None,
    page_size_override: int | None = None,
) -> type[_FakeForestClient]:
    _FakeForestClient.instances = []
    _FakeForestClient.forests = forests
    _FakeForestClient.arboretums = arboretums
    _FakeForestClient.declared_total = declared_total
    _FakeForestClient.page_size_override = page_size_override
    module = ModuleType("krforest")
    module.__dict__["ForestClient"] = _FakeForestClient
    module.__dict__["ForestNoDataError"] = _FakeForestNoDataError
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


def test_krforest_recreation_forests_walks_every_page() -> None:
    """선언 건수가 여러 페이지면 전부 걷는다 — 첫 페이지에서 멈추지 않는다."""

    forests = [object() for _ in range(7)]

    def _run(monkeypatch: pytest.MonkeyPatch) -> list[object]:
        fake = _install_fake_krforest(
            monkeypatch, forests=forests, arboretums=[], page_size_override=3
        )
        settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("forest-key"))
        records = asyncio.run(_acollect(fetch_krforest_recreation_forests(settings)))
        assert fake.instances[0].travel.page_calls == [1, 2, 3]
        return records

    monkeypatch = pytest.MonkeyPatch()
    try:
        records = _run(monkeypatch)
    finally:
        monkeypatch.undo()
    assert len(records) == 7


def test_krforest_recreation_forests_refuses_to_walk_past_the_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """상한을 넘기면 **조용히 자르지 않고** 실패한다.

    upstream이 선언 건수를 거짓으로 크게 말하는 상황을 만든다. 페이지는 계속
    만재로 돌아오므로 짧은 페이지 휴리스틱도 멈추지 않는다 — 이때 상한이 없으면
    요청이 upstream이 말한 숫자를 따라간다.
    """

    forests = [object() for _ in range(1000)]
    _install_fake_krforest(
        monkeypatch,
        forests=forests,
        arboretums=[],
        declared_total=10**9,
        page_size_override=1,
    )
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("forest-key"))

    with pytest.raises(ProviderPaginationOverrun):
        asyncio.run(_acollect(fetch_krforest_recreation_forests(settings)))


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

    agen = fetch_datagokr_cultural_festivals(settings)
    with pytest.raises(ProviderCredentialMissing):
        asyncio.run(agen.__anext__())


def test_fetch_yields_records_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_datagokr(monkeypatch)
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = asyncio.run(_acollect(fetch_datagokr_cultural_festivals(settings)))

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

    async def _take_one_then_close() -> None:
        agen = fetch_datagokr_cultural_festivals(settings)
        first = await agen.__anext__()
        assert first is not None
        # 조기 종료 시에도 finally의 ``aclose()``가 실행되어 client가 닫혀야 한다.
        await agen.aclose()

    asyncio.run(_take_one_then_close())

    assert fake.instances[0].closed is True


def test_standard_museums_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    agen = fetch_standard_museums(settings)
    with pytest.raises(ProviderCredentialMissing):
        asyncio.run(agen.__anext__())


def test_standard_museums_fetch_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_datagokr(monkeypatch)
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = asyncio.run(_acollect(fetch_standard_museums(settings)))

    assert len(records) == 3
    client = fake.instances[0]
    assert client.api_key == "service-key"
    assert client.closed is True


class _FakeFestivalPage:
    """실물 ``visitkorea.models.Page``의 필드 계약(``items`` + ``total_count`` + ``raw``)."""

    def __init__(
        self,
        items: list[object],
        *,
        total_count: int | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        self.items = tuple(items)
        self.total_count = len(items) if total_count is None else total_count
        self.raw = raw


class _FakeVisitKoreaClient:
    instances: list[_FakeVisitKoreaClient] = []
    items: list[object] = []
    declared_total: int | None = None
    page_size_override: int | None = None
    never_advances: bool = False

    def __init__(self, *, service_key: str | None = None, **_kwargs: Any) -> None:
        self.service_key = service_key
        self.closed = False
        self.search_calls: list[Any] = []
        self.page_calls: list[int] = []
        _FakeVisitKoreaClient.instances.append(self)

    async def search_festival(
        self, event_start_date: Any, *, page_no: int = 1, num_of_rows: int = 10, **_kw: Any
    ) -> _FakeFestivalPage:
        self.search_calls.append(event_start_date)
        self.page_calls.append(page_no)
        size = type(self).page_size_override or num_of_rows
        effective_page = 1 if type(self).never_advances else page_no
        start = (effective_page - 1) * size
        items = type(self).items
        return _FakeFestivalPage(
            items[start : start + size],
            total_count=(
                len(items)
                if type(self).declared_total is None
                else type(self).declared_total
            ),
            # 실물 `visitkorea.models.Page`는 파싱 전 body를 `raw`로 들고 있다.
            # 대역이 그것을 흉내내지 않으면 `fingerprint`가 늘 None이 되어
            # **전진 검사가 호출 지점에서 한 번도 돌지 않는다**(2차 리뷰 지적).
            raw={
                "pageNo": effective_page,
                "items": [id(item) for item in items[start : start + size]],
            },
        )

    # ``iter_pages``는 일부러 두지 않는다 — 라이브러리 iterator는 ``max_pages``가
    # 없으면 상한이 없다. 프로덕션이 그쪽으로 되돌아가면 AttributeError로 빨개진다.

    # 실물 ``visitkorea.KrTourApiClient``의 정리 메서드는 ``async def aclose``
    # 하나다(``visitkorea/client.py:157``; 동기 ``close``는 없다). 대역에 동기
    # ``close``를 남겨 두면 fetcher가 동기 정리로 되돌아가도 초록이 된다.
    async def aclose(self) -> None:
        self.closed = True


def _install_fake_visitkorea(
    monkeypatch: pytest.MonkeyPatch,
    *,
    items: list[object],
    declared_total: int | None = None,
    page_size_override: int | None = None,
    never_advances: bool = False,
) -> type[_FakeVisitKoreaClient]:
    _FakeVisitKoreaClient.instances = []
    _FakeVisitKoreaClient.items = items
    _FakeVisitKoreaClient.declared_total = declared_total
    _FakeVisitKoreaClient.page_size_override = page_size_override
    _FakeVisitKoreaClient.never_advances = never_advances
    module = ModuleType("visitkorea")
    module.__dict__["KrTourApiClient"] = _FakeVisitKoreaClient
    monkeypatch.setitem(sys.modules, "visitkorea", module)
    return _FakeVisitKoreaClient


async def test_visitkorea_festival_events_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    generator = fetch_visitkorea_festival_events(settings)
    with pytest.raises(ProviderCredentialMissing):
        await anext(generator)


async def test_visitkorea_festival_events_fetch_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_visitkorea(monkeypatch, items=[object(), object()])
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = await _acollect(fetch_visitkorea_festival_events(settings))

    assert len(records) == 2
    client = fake.instances[0]
    assert client.service_key == "service-key"
    assert client.closed is True
    # search_festival에 event_start_date(올해 1월 1일)를 넘긴다.
    assert client.search_calls
    assert client.search_calls[0].month == 1


async def test_visitkorea_festival_events_walks_every_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """축제는 한 페이지에 다 담기지 않는다 — 전부 걷는지 본다."""

    items = [object() for _ in range(5)]
    fake = _install_fake_visitkorea(monkeypatch, items=items, page_size_override=2)
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = await _acollect(fetch_visitkorea_festival_events(settings))

    assert len(records) == 5
    assert fake.instances[0].page_calls == [1, 2, 3]


async def test_visitkorea_festival_events_refuses_to_walk_past_the_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """visitkorea ``iter_paginated_pages``는 ``max_pages``가 없으면 상한이 없다."""

    items = [object() for _ in range(1000)]
    _install_fake_visitkorea(
        monkeypatch, items=items, declared_total=10**9, page_size_override=1
    )
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    with pytest.raises(ProviderPaginationOverrun):
        await _acollect(fetch_visitkorea_festival_events(settings))


class _FakeBeachPage:
    def __init__(self, items: list[object]) -> None:
        self.items = tuple(items)


class _FakeKhoaClient:
    instances: list[_FakeKhoaClient] = []
    per_sido: list[object] = []

    def __init__(self, *, api_key: str | None = None, **kwargs: Any) -> None:
        self.api_key = api_key
        self.kwargs = kwargs
        self.closed = False
        self.calls: list[str] = []
        _FakeKhoaClient.instances.append(self)

    # khoa 6.x(provider PR#13)는 sync 진입점을 전부 없앴다. fake가 옛 표면을 들고
    # 있으면 실제 파손을 못 잡는다 — 실제로 그랬다.
    async def aoceans_beach_info(
        self, sido_nm: str, *, page_no: int = 1, num_of_rows: int = 100, **_kw: Any
    ) -> _FakeBeachPage:
        self.calls.append(sido_nm)
        # 단일 페이지(short)만 반환 → 페이지네이션 stop.
        return _FakeBeachPage(list(type(self).per_sido) if page_no == 1 else [])

    async def aclose(self) -> None:
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


async def test_khoa_beaches_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    generator = fetch_khoa_beaches(settings)
    with pytest.raises(ProviderCredentialMissing):
        await anext(generator)


async def test_khoa_beaches_fetch_iterates_sido_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_khoa(
        monkeypatch, sidos=("부산광역시", "강원특별자치도"), per_sido=[object(), object()]
    )
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = [record async for record in fetch_khoa_beaches(settings)]

    # 2 sido × 2 record = 4.
    assert len(records) == 4
    client = fake.instances[0]
    assert client.calls == ["부산광역시", "강원특별자치도"]
    assert client.kwargs == {"timeout": 20.0, "retries": 1}
    assert client.closed is True


class _FakeKhoaNetworkError(Exception):
    retryable = True
    failure_kind = "network"


class _FlakyKhoaClient(_FakeKhoaClient):
    fail_first = True

    async def aoceans_beach_info(
        self, sido_nm: str, *, page_no: int = 1, num_of_rows: int = 100, **kw: Any
    ) -> _FakeBeachPage:
        if type(self).fail_first:
            type(self).fail_first = False
            self.calls.append(sido_nm)
            raise _FakeKhoaNetworkError("transient")
        return await super().aoceans_beach_info(
            sido_nm,
            page_no=page_no,
            num_of_rows=num_of_rows,
            **kw,
        )


async def test_khoa_beaches_retries_transient_page_without_record_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeKhoaClient.instances = []
    _FakeKhoaClient.per_sido = [object(), object()]
    _FlakyKhoaClient.fail_first = True
    module = ModuleType("khoa")
    module.__dict__["KhoaClient"] = _FlakyKhoaClient
    module.__dict__["OCEANS_BEACH_INFO_DEFAULT_SIDO_NAMES"] = ("부산광역시",)
    monkeypatch.setitem(sys.modules, "khoa", module)
    delays: list[float] = []

    async def _instant_sleep(delay: float) -> None:
        delays.append(delay)

    # async 경계의 backoff는 `asyncio.sleep`으로 간다 — `time.sleep`을 막아도
    # 아무 일도 일어나지 않는다.
    monkeypatch.setattr(
        provider_fetchers.upstream_retry,
        "asyncio",
        SimpleNamespace(sleep=_instant_sleep),
    )
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("svc"))

    records = [record async for record in fetch_khoa_beaches(settings)]

    assert len(records) == 2
    client = _FakeKhoaClient.instances[0]
    assert client.calls == ["부산광역시", "부산광역시"]
    assert delays == [15.0]
    assert client.closed is True


def test_khoa_real_exception_contract_matches_default_retry_predicate() -> None:
    khoa_exceptions = pytest.importorskip("khoa.exceptions")
    network = khoa_exceptions.KhoaRequestError(
        "t", failure_kind="network", retryable=True
    )
    quota = khoa_exceptions.KhoaRequestError(
        "t", failure_kind="quota", retryable=True
    )

    assert provider_fetchers.upstream_retry.default_upstream_retryable(network) is True
    assert provider_fetchers.upstream_retry.default_upstream_retryable(quota) is False


def test_standard_tourist_attractions_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    agen = fetch_standard_tourist_attractions(settings)
    with pytest.raises(ProviderCredentialMissing):
        asyncio.run(agen.__anext__())


def test_standard_tourist_attractions_fetch_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_datagokr(monkeypatch)
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = asyncio.run(_acollect(fetch_standard_tourist_attractions(settings)))

    assert len(records) == 2
    assert fake.instances[0].closed is True


def test_standard_parking_lots_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    agen = fetch_standard_parking_lots(settings)
    with pytest.raises(ProviderCredentialMissing):
        asyncio.run(agen.__anext__())


def test_standard_parking_lots_fetch_yields_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_datagokr(monkeypatch)
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = asyncio.run(_acollect(fetch_standard_parking_lots(settings)))

    assert len(records) == 4
    assert fake.instances[0].closed is True


async def test_krheritage_fetch_raises_when_credential_missing() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)

    generator = fetch_krheritage_events(settings)
    with pytest.raises(ProviderCredentialMissing):
        await anext(generator)


async def test_krheritage_fetch_yields_records_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_krheritage(monkeypatch)
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    records = [record async for record in fetch_krheritage_events(settings)]

    assert len(records) == 2
    assert len(fake.instances) == 1
    client = fake.instances[0]
    assert client.api_key == "service-key"
    assert client.closed is True
    # 창은 Map이 소유한다 — 지난달 1개 + 이번 달 + 다음 12개월.
    assert len(client.event.calls) == 14, (
        "rolling window가 14개월이 아니다 — 이 수가 곧 이 fetcher의 요청 수다"
    )
    assert len(set(client.event.calls)) == 14, "같은 달을 두 번 불렀다"


async def test_krheritage_items_fetch_is_keyless_iterates_kind_codes_and_closes(
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

    records = [record async for record in fetch_krheritage_items(settings)]

    assert len(records) == 3
    assert len(fake.instances) == 1
    client = fake.instances[0]
    assert client.api_key is None
    assert client.closed is True
    # 종목코드별 search.list(page_size=100, page=1, ccba_kdcd=...) 1회씩.
    assert client.search.calls == [(100, "11"), (100, "13")]


async def test_krheritage_items_fetch_stops_at_max_items_per_run(
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

    records = [record async for record in fetch_krheritage_items(settings)]

    # detail 1콜/건 보호 — 상한 2에서 중단, 두 번째 종목코드(12)는 미호출.
    assert len(records) == 2
    client = fake.instances[0]
    assert client.closed is True
    assert client.search.calls == [(100, "11")]


async def test_krheritage_items_fetch_surfaces_a_client_without_aclose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """정리는 **무조건** 일어난다 — ``getattr`` guard로 건너뛰지 않는다.

    fetcher는 종전 ``getattr(client, "close", None)`` guard를 버리고
    ``await client.aclose()`` 하나만 남겼다. 실물에 sync ``close``가 없기
    때문이다(``krheritage/client.py:80``에 ``aclose``만 있다). guard가
    되살아나면 ``aclose``가 없는 client는 조용히 지나가고 세션이 샌다 —
    그 조용함을 여기서 깬다.
    """

    class _NoAcloseHeritageClient:
        instances: list[Any] = []

        def __init__(self, *, api_key: str | None = None, **_kwargs: Any) -> None:
            self.api_key = api_key
            self.closed = False
            self.search = _FakeHeritageSearchService({"11": [object()]})
            _NoAcloseHeritageClient.instances.append(self)

        def close(self) -> None:  # 구 계약 — 실물에는 없는 이름이다.
            self.closed = True

    _NoAcloseHeritageClient.instances = []
    module = ModuleType("krheritage")
    module.__dict__["HeritageClient"] = _NoAcloseHeritageClient
    monkeypatch.setitem(sys.modules, "krheritage", module)
    settings = KorTravelMapSettings(krheritage_kind_codes="11")

    with pytest.raises(AttributeError, match="aclose"):
        [record async for record in fetch_krheritage_items(settings)]

    assert _NoAcloseHeritageClient.instances[0].closed is False, (
        "sync ``close``로 대신 닫혔다 — fetcher가 다시 guard를 쓰고 있다"
    )


def test_live_resource_returns_iterable_when_credentials_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY", "service-key")
    sentinel = [object(), object()]

    def _fake_fetch(_settings: KorTravelMapSettings) -> Iterable[Any]:
        return sentinel

    resource_def = build_provider_record_live_resource(_DATAGOKR_SPEC, _fake_fetch)
    resource_fn = cast("Callable[[object], object]", resource_def.resource_fn)

    result = resource_fn(_guarded_init_resource_context())

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

    result = resource_fn(_guarded_init_resource_context())

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
        resource_fn(_guarded_init_resource_context())

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


def test_krforest_first_page_nodata_is_a_failure_not_an_empty_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """첫 페이지 NODATA를 **삼키지 않는다**.

    krforest fetcher는 authoritative snapshot 적재로 흘러가고, 등산로·둘레길은
    `retire_absent_from_snapshot=True`로 적재된다 — 빈 snapshot 하나가 그 source의
    feature를 **전부 은퇴**시킨다. 종전 라이브러리 iterator는 `ForestNoDataError`를
    잡지 않아 asset이 시끄럽게 죽었는데, 저장소 헬퍼로 옮기며 `end_of_pages`를 단
    것이 그 신호를 조용한 0행 성공으로 바꿨다(2026-09-13 적대 리뷰가 잡았다).
    """

    fake = _install_fake_krforest(monkeypatch, forests=[], arboretums=[])
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("forest-key"))

    with pytest.raises(_FakeForestNoDataError):
        asyncio.run(_acollect(fetch_krforest_recreation_forests(settings)))
    assert fake.instances[0].closed is True


def test_krforest_nodata_after_the_first_page_is_a_normal_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """과분류 방지 — 마지막 페이지 다음의 NODATA는 정상 종료다."""

    forests = [object() for _ in range(3)]
    _install_fake_krforest(
        monkeypatch, forests=forests, arboretums=[], page_size_override=3
    )
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("forest-key"))

    records = asyncio.run(_acollect(fetch_krforest_recreation_forests(settings)))

    assert len(records) == 3


async def test_visitkorea_stalled_pagination_is_caught_at_the_call_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전진 검사가 **호출 지점에서** 실제로 도는지 본다.

    헬퍼 쪽 테스트만 있으면 `_page`가 `fingerprint`를 안 넘겨도 초록이다 —
    2차 적대 리뷰가 정확히 그 상태를 잡았다(대역에 `raw`가 없어 fingerprint가
    늘 None이었다).
    """

    items = [object() for _ in range(10)]
    _install_fake_visitkorea(
        monkeypatch, items=items, declared_total=3000, page_size_override=2,
        never_advances=True,
    )
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))

    with pytest.raises(ProviderPaginationStalled):
        await _acollect(fetch_visitkorea_festival_events(settings))
