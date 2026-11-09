"""TourAPI 관광지 live source·상세 예산 asset 경로(#1459).

provider 라이브러리 대신 ``visitkorea`` 모듈 대역을 심는다 — fetcher가 import 시점이 아니라
호출 시점에 ``importlib.import_module("visitkorea")``를 하므로 그 대역이 그대로 쓰인다.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

from kortravelmap.dagster import assets
from kortravelmap.dagster.provider_fetchers import (
    ProviderCredentialMissing,
    VisitKoreaAttractionSnapshotIncomplete,
    VisitKoreaAttractionSource,
    fetch_visitkorea_tourist_attractions,
)
from kortravelmap.dagster.upstream_requests import counting_upstream_requests

KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class _Row:
    content_id: str
    overview: str | None = None
    homepage: str | None = None
    modified_time: datetime | None = None


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
    declared: int = 0
    detail_errors: dict[str, str] = {}

    def __init__(self, *, service_key: str, **_: Any) -> None:
        self.service_key = service_key
        self.closed = False
        self.list_calls: list[dict[str, Any]] = []
        self.detail_calls: list[str] = []
        _FakeClient.instances.append(self)

    async def area_based_list(self, **kwargs: Any) -> _Page:
        self.list_calls.append(kwargs)
        page_no = kwargs["page_no"]
        items = type(self).pages.get(page_no, [])
        return _Page(items, type(self).declared, raw={"page": page_no})

    async def detail_common(self, content_id: str) -> Any:
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
    _FakeClient.declared = 0
    _FakeClient.detail_errors = {}
    module = ModuleType("visitkorea")
    module.__dict__["KrTourApiClient"] = _FakeClient
    monkeypatch.setitem(sys.modules, "visitkorea", module)
    return _FakeClient


def _source() -> VisitKoreaAttractionSource:
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("service-key"))
    return fetch_visitkorea_tourist_attractions(settings)


async def _drain(source: VisitKoreaAttractionSource) -> list[Any]:
    return [record async for record in source]


def test_missing_credential_is_refused() -> None:
    settings = KorTravelMapSettings(data_go_kr_service_key=None)
    with pytest.raises(ProviderCredentialMissing):
        fetch_visitkorea_tourist_attractions(settings)


async def test_the_list_walks_every_page_of_content_type_12_and_closes(
    fake: type[_FakeClient],
) -> None:
    fake.pages = {1: [_Row(str(n)) for n in range(1000)], 2: [_Row("x1"), _Row("x2")]}
    fake.declared = 1002

    with counting_upstream_requests() as counter:
        records = await _drain(_source())

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
    fake.pages = {1: [_Row(str(n)) for n in range(1000)]}
    fake.declared = 1500

    with pytest.raises(VisitKoreaAttractionSnapshotIncomplete, match="1500건 중 고유 1000건"):
        await _drain(_source())
    assert fake.instances[0].closed is True


async def test_a_row_repeated_across_pages_is_not_counted_twice(
    fake: type[_FakeClient],
) -> None:
    # 순회 중 삭제가 일어나면 한 행이 빠지고 다른 행이 두 번 온다 — 개수만 세면 통과한다.
    first = [_Row(str(n)) for n in range(1000)]
    fake.pages = {1: first, 2: [first[-1]]}
    fake.declared = 1001

    with pytest.raises(VisitKoreaAttractionSnapshotIncomplete):
        await _drain(_source())


async def test_details_are_fetched_and_counted(fake: type[_FakeClient]) -> None:
    with counting_upstream_requests() as counter:
        details = await _source().fetch_details(["1", "2"])

    assert details == {"1": ("설명 1", ""), "2": ("설명 2", "")}
    assert counter[0] == 2
    assert fake.instances[0].closed is True


async def test_details_stop_at_the_daily_limit(fake: type[_FakeClient]) -> None:
    fake.detail_errors = {"2": "rate_limit"}

    details = await _source().fetch_details(["1", "2", "3"])

    assert details == {"1": ("설명 1", "")}
    assert fake.instances[0].detail_calls == ["1", "2"]  # 한도 뒤로는 부르지 않는다


async def test_a_single_failed_detail_is_skipped(fake: type[_FakeClient]) -> None:
    fake.detail_errors = {"2": "no_data"}

    details = await _source().fetch_details(["1", "2", "3"])

    assert set(details) == {"1", "3"}


async def test_details_with_no_ids_open_no_client(fake: type[_FakeClient]) -> None:
    assert await _source().fetch_details([]) == {}
    assert fake.instances == []


# -- asset: 저장 상세 재사용 + 예산 -----------------------------------------


class _StoredClient:
    def __init__(self, stored: list[Any]) -> None:
        self.stored = stored
        self.reads: list[dict[str, str]] = []

    async def read_current_source_records(self, **kwargs: str) -> tuple[list[Any], int]:
        self.reads.append(kwargs)
        return self.stored, len(self.stored)


class _Source:
    def __init__(self) -> None:
        self.requested: list[str] = []

    async def fetch_details(self, content_ids: Any) -> dict[str, tuple[str, str]]:
        self.requested.extend(content_ids)
        return {cid: (f"새 설명 {cid}", "") for cid in content_ids}


def _context(client: object) -> Any:
    return SimpleNamespace(
        resources=SimpleNamespace(kor_travel_map_client=client),
        log=SimpleNamespace(info=lambda *_a, **_k: None),
    )


_T = datetime(2026, 11, 1, 9, 0, tzinfo=KST)


async def test_attach_reuses_stored_detail_and_fetches_the_rest_within_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(assets, "VISITKOREA_ATTRACTION_DETAIL_BUDGET", 2)
    stored = [
        SimpleNamespace(
            source_entity_id="a",
            raw_data={"modified_time": _T.isoformat(), "overview": "저장 설명", "homepage": ""},
        )
    ]
    client = _StoredClient(stored)
    source = _Source()
    records = [_Row("a", modified_time=_T), _Row("b"), _Row("c"), _Row("d")]

    attached = await assets._attach_attraction_details(_context(client), source, records)

    assert client.reads == [
        {"provider": "python-visitkorea-api", "dataset_key": "visitkorea_tourist_attractions"}
    ]
    assert source.requested == ["b", "c"]
    assert [(r.content_id, r.overview) for r in attached] == [
        ("a", "저장 설명"),
        ("b", "새 설명 b"),
        ("c", "새 설명 c"),
        ("d", None),  # 예산 밖 — 다음 run이 받는다
    ]


async def test_attach_without_a_detail_capable_source_only_reuses() -> None:
    client = _StoredClient([])
    attached = await assets._attach_attraction_details(
        _context(client), object(), [_Row("a"), _Row("b")]
    )
    assert [r.overview for r in attached] == [None, None]
