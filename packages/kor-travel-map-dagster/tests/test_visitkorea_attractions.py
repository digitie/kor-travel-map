"""TourAPI 관광지 fetcher·상세 예산 asset 경로(#1459).

fetcher 테스트는 provider 라이브러리 대신 ``visitkorea`` 모듈 대역을 심는다 — fetcher가 호출
시점에 ``importlib.import_module("visitkorea")``를 하므로 그 대역이 쓰인다. 대역 메서드의 이름·
인자는 실물(``visitkorea/client.py``: ``area_based_list(*, content_type_id, arrange, page_no,
num_of_rows)``, ``detail_common(content_id)``, ``aclose()``)과 같다. asset 테스트는 실물
``TourItem``으로 돈다(frozen pydantic — ``model_copy`` 경로를 그대로 탄다).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from kortravelmap.dto import Address, Coordinate
from kortravelmap.providers.visitkorea_attractions import (
    VisitKoreaAttractionItem,
    tourapi_attractions_to_bundles,
)
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

from dagster import Failure
from kortravelmap.dagster import assets
from kortravelmap.dagster.provider_fetchers import (
    ProviderCredentialMissing,
    VisitKoreaAttractionSnapshotIncomplete,
    fetch_visitkorea_attraction_details,
    fetch_visitkorea_tourist_attractions,
)
from kortravelmap.dagster.upstream_requests import counting_upstream_requests

KST = timezone(timedelta(hours=9))
_SETTINGS = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))


class _Page:
    def __init__(self, items: list[Any], total: int, raw: object) -> None:
        self.items = tuple(items)
        self.total_count = total
        self.raw = raw


class _ProviderError(Exception):
    def __init__(self, failure_kind: str) -> None:
        super().__init__(failure_kind)
        self.failure_kind = failure_kind


class _FakeClient:
    instances: list[_FakeClient] = []
    pages: dict[int, list[Any]] = {}
    totals: dict[int, int] = {}
    detail_errors: dict[str, str] = {}

    def __init__(self, service_key: str | None = None, **_: Any) -> None:
        self.service_key = service_key
        self.closed = False
        self.list_calls: list[dict[str, Any]] = []
        self.detail_calls: list[str] = []
        _FakeClient.instances.append(self)

    async def area_based_list(
        self,
        *,
        content_type_id: str | None = None,
        arrange: str | None = None,
        page_no: int = 1,
        num_of_rows: int = 10,
    ) -> _Page:
        self.list_calls.append(
            {
                "content_type_id": content_type_id,
                "arrange": arrange,
                "page_no": page_no,
                "num_of_rows": num_of_rows,
            }
        )
        cls = type(self)
        return _Page(cls.pages.get(page_no, []), cls.totals[page_no], raw={"page": page_no})

    async def detail_common(self, content_id: str, *, page_no: int = 1, num_of_rows: int = 10) -> Any:
        self.detail_calls.append(content_id)
        kind = type(self).detail_errors.get(content_id)
        if kind is not None:
            raise _ProviderError(kind)
        return SimpleNamespace(overview=f"설명 {content_id}", homepage=None)

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> type[_FakeClient]:
    _FakeClient.instances = []
    _FakeClient.pages = {}
    _FakeClient.totals = {}
    _FakeClient.detail_errors = {}
    module = ModuleType("visitkorea")
    module.__dict__["KrTourApiClient"] = _FakeClient
    monkeypatch.setitem(sys.modules, "visitkorea", module)
    return _FakeClient


def _rows(*ids: str) -> list[Any]:
    return [SimpleNamespace(content_id=content_id) for content_id in ids]


async def _drain() -> list[Any]:
    return [record async for record in fetch_visitkorea_tourist_attractions(_SETTINGS)]


async def test_missing_credential_is_refused() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)
    with pytest.raises(ProviderCredentialMissing):
        await fetch_visitkorea_tourist_attractions(settings).__anext__()
    with pytest.raises(ProviderCredentialMissing):
        await fetch_visitkorea_attraction_details(settings, ["1"])


async def test_the_list_walks_every_page_of_content_type_12_and_closes(
    fake: type[_FakeClient],
) -> None:
    fake.pages = {1: _rows(*(str(n) for n in range(1000))), 2: _rows("x1", "x2")}
    fake.totals = {1: 1002, 2: 1002}

    with counting_upstream_requests() as counter:
        records = await _drain()

    assert len(records) == 1002
    (client,) = fake.instances
    assert client.service_key == "service-key"
    assert client.closed is True
    assert [call["page_no"] for call in client.list_calls] == [1, 2]
    assert {call["content_type_id"] for call in client.list_calls} == {"12"}
    # 수정일순은 순회 중 수정된 행을 다른 페이지로 옮긴다 — 생성일순이어야 한다.
    assert {call["arrange"] for call in client.list_calls} == {"D"}
    assert {call["num_of_rows"] for call in client.list_calls} == {1000}
    assert counter[0] == 2


async def test_a_short_list_fails_before_retiring_anything(fake: type[_FakeClient]) -> None:
    # 2페이지가 비어 오면 1,000건 밖의 관광지가 전부 은퇴한다 — 선언보다 적으면 실패.
    fake.pages = {1: _rows(*(str(n) for n in range(1000)))}
    fake.totals = {1: 1500, 2: 1500}

    with pytest.raises(VisitKoreaAttractionSnapshotIncomplete, match="1500건 중 고유 1000건"):
        await _drain()
    assert fake.instances[0].closed is True


async def test_a_list_that_changes_during_the_walk_fails(fake: type[_FakeClient]) -> None:
    # 삭제 하나와 등록 하나가 겹치면 개수는 맞아도 경계 행 하나가 빠질 수 있다.
    first = _rows(*(str(n) for n in range(1000)))
    fake.pages = {1: first, 2: _rows("new")}
    fake.totals = {1: 1001, 2: 1002}

    with pytest.raises(VisitKoreaAttractionSnapshotIncomplete, match="바뀌었다"):
        await _drain()


async def test_a_row_repeated_across_pages_is_not_counted_twice(
    fake: type[_FakeClient],
) -> None:
    first = _rows(*(str(n) for n in range(1000)))
    fake.pages = {1: first, 2: [first[-1]]}
    fake.totals = {1: 1001, 2: 1001}

    with pytest.raises(VisitKoreaAttractionSnapshotIncomplete, match="고유 1000건"):
        await _drain()


async def test_details_are_fetched_counted_and_closed(fake: type[_FakeClient]) -> None:
    with counting_upstream_requests() as counter:
        details = await fetch_visitkorea_attraction_details(_SETTINGS, ["1", "2"])

    assert details == {"1": ("설명 1", ""), "2": ("설명 2", "")}
    assert counter[0] == 2
    assert fake.instances[0].closed is True


async def test_details_stop_at_the_daily_limit(fake: type[_FakeClient]) -> None:
    fake.detail_errors = {"2": "rate_limit"}

    details = await fetch_visitkorea_attraction_details(_SETTINGS, ["1", "2", "3"])

    assert details == {"1": ("설명 1", "")}
    assert fake.instances[0].detail_calls == ["1", "2"]  # 한도 뒤로는 부르지 않는다


async def test_no_detail_upstream_is_stored_as_received_empty(fake: type[_FakeClient]) -> None:
    # 원천에 상세가 없다는 답은 "받았다"로 남겨야 매 run 예산을 다시 쓰지 않는다.
    fake.detail_errors = {"2": "no_data", "3": "server"}

    details = await fetch_visitkorea_attraction_details(_SETTINGS, ["1", "2", "3", "4"])

    assert details == {"1": ("설명 1", ""), "2": ("", ""), "4": ("설명 4", "")}


async def test_details_with_no_ids_open_no_client(fake: type[_FakeClient]) -> None:
    assert await fetch_visitkorea_attraction_details(_SETTINGS, []) == {}
    assert fake.instances == []


# -- asset: 실물 TourItem으로 저장 상세 재사용·예산·재시도 ------------------------------------

_T = datetime(2026, 11, 1, 9, 0, tzinfo=KST)


def _tour_item(content_id: str, **fields: Any) -> Any:
    visitkorea = pytest.importorskip("visitkorea")
    base: dict[str, Any] = {
        name: None for name in visitkorea.TourItem.model_fields if name != "raw"
    }
    base.update(
        content_id=content_id,
        content_type_id="12",
        title=f"관광지 {content_id}",
        map_x=129.03,
        map_y=35.10,
        modified_time=_T,
        raw={"contentid": content_id},
    )
    base.update(fields)
    return visitkorea.TourItem.model_validate(base)


def test_the_real_tour_item_satisfies_the_protocol() -> None:
    assert isinstance(_tour_item("1"), VisitKoreaAttractionItem)


class _StoredClient:
    def __init__(self, stored: list[Any]) -> None:
        self.stored = stored
        self.reads: list[dict[str, str]] = []

    async def read_current_source_records(self, **kwargs: str) -> tuple[list[Any], int]:
        self.reads.append(kwargs)
        return self.stored, len(self.stored)


def _context(client: object, *, retry_number: int = 0) -> Any:
    return SimpleNamespace(
        resources=SimpleNamespace(kor_travel_map_client=client),
        log=SimpleNamespace(info=lambda *_a, **_k: None),
        retry_number=retry_number,
    )


@pytest.fixture
def requested(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    async def _details(settings: Any, content_ids: Any) -> dict[str, tuple[str, str]]:
        del settings
        seen.extend(content_ids)
        return {cid: (f"새 설명 {cid}", "") for cid in content_ids}

    monkeypatch.setattr(assets, "fetch_visitkorea_attraction_details", _details)
    return seen


async def test_attach_reuses_stored_detail_and_fetches_the_rest_within_budget(
    monkeypatch: pytest.MonkeyPatch, requested: list[str]
) -> None:
    monkeypatch.setattr(assets, "VISITKOREA_ATTRACTION_DETAIL_BUDGET", 2)
    stored = [
        SimpleNamespace(
            source_entity_id="a",
            raw_data={"modified_time": _T.isoformat(), "overview": "저장 설명", "homepage": ""},
        )
    ]
    client = _StoredClient(stored)
    records = [_tour_item(cid) for cid in ("a", "b", "c", "d")]

    attached = await assets._attach_attraction_details(_context(client), records)

    assert client.reads == [
        {"provider": "python-visitkorea-api", "dataset_key": "visitkorea_tourist_attractions"}
    ]
    assert requested == ["b", "c"]
    assert [(r.content_id, r.overview) for r in attached] == [
        ("a", "저장 설명"),
        ("b", "새 설명 b"),
        ("c", "새 설명 c"),
        ("d", None),  # 예산 밖 — 다음 run이 받는다
    ]


async def test_a_retried_step_does_not_spend_the_detail_budget_again(
    requested: list[str],
) -> None:
    client = _StoredClient([])
    records = [_tour_item("a"), _tour_item("b")]

    attached = await assets._attach_attraction_details(
        _context(client, retry_number=1), records
    )

    assert requested == []
    assert [r.overview for r in attached] == [None, None]


# -- 역지오코딩 결손 상한(drop 모드가 은퇴로 번지지 않게) --------------------------------------


async def _bundles(count: int, *, unresolved: int) -> list[Any]:
    async def _reverse(coord: Coordinate) -> Address | None:
        del coord
        return None

    async def _resolved(coord: Coordinate) -> Address:
        del coord
        return Address(bjd_code="2611010100", sigungu_code="26110", sido_code="26")

    items = [_tour_item(str(n)) for n in range(count)]
    good = await tourapi_attractions_to_bundles(
        items[unresolved:], fetched_at=_T, reverse_geocoder=_resolved
    )
    bad = await tourapi_attractions_to_bundles(
        items[:unresolved], fetched_at=_T, reverse_geocoder=_reverse
    )
    return [*bad, *good]


async def test_a_few_unresolved_rows_are_tolerated() -> None:
    assets._ensure_geo_resolved_enough(await _bundles(40, unresolved=30))


async def test_a_geo_outage_stops_before_retiring() -> None:
    with pytest.raises(Failure, match="법정동을 못 받았다"):
        assets._ensure_geo_resolved_enough(await _bundles(40, unresolved=31))
