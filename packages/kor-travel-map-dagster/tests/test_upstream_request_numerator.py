"""분자가 **generator를 지나 asset metadata까지 닿는지** 결박한다.

조문 2의 절반이 오래 열려 있던 이유는 배선이 없어서였다 — 요청을 세는 자리(페이지
루프)와 그 수를 내보내는 자리(asset output metadata) 사이에 fetcher generator가
몇 겹 끼어 있었다. 실행 문맥(:class:`contextvars.ContextVar`)이 그 배선을 대신한다.

**그러니 여기서 재야 하는 것은 "계수기가 는다"가 아니라 "generator를 지나서도
는다"이다.** 전자만 재면 배선이 끊어져도 초록이다 — 이 저장소가 반복한 실패 모양이다
(2026-09-13 적대 리뷰가 같은 형태를 세 번 잡았다).
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Iterator
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from dagster import Failure
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

from kortravelmap.dagster.provider_fetchers import (
    _OpinetCallBudget,
    fetch_datagokr_file_data_records,
    fetch_krheritage_events,
    fetch_krheritage_items,
    fetch_opinet_station_price_details,
)
from kortravelmap.dagster.provider_pagination import (
    ProviderPage,
    aiter_paginated_items,
    iter_paginated_items,
)
from kortravelmap.dagster.quota_exhaustion import (
    raise_terminal_if_quota_exhausted,
)
from kortravelmap.dagster.upstream_requests import (
    UPSTREAM_REQUESTS_METADATA_KEY,
    counting_upstream_requests,
    note_upstream_request,
    observed_upstream_requests,
)


def test_without_a_scope_counting_is_a_no_op() -> None:
    """계수기를 열지 않은 경로에서 죽지 않는다 — 단위 테스트·수동 호출."""

    note_upstream_request()
    assert observed_upstream_requests() is None


def test_an_uninstrumented_path_reports_nothing_not_zero() -> None:
    """**계수기가 열려 있어도 한 번도 기록되지 않았으면 ``None``이다.**

    이것이 2026-09-13 적대 리뷰가 잡은 blocker의 핵심이다. 계수기는 asset 35개
    전부에서 열리는데 세는 자리는 셋뿐이었고, 그래서 계측되지 않은 fetcher가
    "0번 요청했다"고 보고했다 — 하필 저장소가 유일하게 한도 대비 run 예산을 코드에
    박아 둔 provider(OpiNet, `_OPINET_RUN_CALL_BUDGET` vs 무료키 300/일)가
    수천 건을 쓰면서 0을 냈다. 운영자가 그 0을 "요청이 없었다"로 읽으면 정반대
    결론에 이른다.
    """

    assert observed_upstream_requests() is None
    with counting_upstream_requests():
        assert observed_upstream_requests() is None, (
            "기록이 없는데 0을 냈다 — 계측되지 않은 fetcher가 0으로 위장한다"
        )
        note_upstream_request(0)
        assert observed_upstream_requests() == 0, (
            "명시적으로 0건을 기록한 것은 관측이다 — 그때는 0을 내야 한다"
        )


def test_the_scope_restores_the_outer_counter() -> None:
    with counting_upstream_requests() as outer:
        note_upstream_request()
        with counting_upstream_requests() as inner:
            note_upstream_request(3)
            assert inner[0] == 3
        assert outer[0] == 1, "안쪽 계수가 바깥으로 새면 이중 계수가 된다"


# ------------------------------------------------------- generator를 지나서도 는가


def test_a_sync_generator_chain_still_reaches_the_counter() -> None:
    """**배선 검사.** fetcher가 generator 두 겹을 지나도 계수기에 닿아야 한다."""

    def _page(page_no: int) -> ProviderPage:
        return ProviderPage(items=[f"p{page_no}"] if page_no <= 3 else [], total_count=3)

    def _fetcher() -> Iterator[Any]:
        yield from iter_paginated_items(_page, num_of_rows=1, label="sync-chain")

    def _outer() -> Iterator[Any]:
        yield from _fetcher()

    with counting_upstream_requests() as counter:
        collected = list(_outer())

    assert collected == ["p1", "p2", "p3"]
    assert counter[0] == 3, (
        f"generator를 지나며 계수가 끊겼다({counter[0]}건) — 실행 문맥 배선을 의심하라"
    )


def test_an_async_generator_chain_still_reaches_the_counter() -> None:
    """async fetcher도 같아야 한다 — krforest 4곳과 khoa가 이 경로다."""

    async def _page(page_no: int) -> ProviderPage:
        return ProviderPage(items=[f"p{page_no}"] if page_no <= 2 else [], total_count=2)

    async def _fetcher() -> AsyncIterator[Any]:
        async for item in aiter_paginated_items(_page, num_of_rows=1, label="async-chain"):
            yield item

    async def _collect() -> list[Any]:
        return [item async for item in _fetcher()]

    async def _run() -> tuple[list[Any], int]:
        with counting_upstream_requests() as counter:
            items = await _collect()
        return items, counter[0]

    collected, counted = asyncio.run(_run())
    assert collected == ["p1", "p2"]
    assert counted == 2, f"async generator를 지나며 계수가 끊겼다({counted}건)"


def test_a_failed_sweep_counts_the_request_that_failed() -> None:
    """실패로 끝난 요청도 쿼터를 쓴다 — **계수기 안에서는** 세진다.

    이 테스트가 재는 것은 계수기까지다. 그 수가 **읽을 수 있는 곳까지 가는지**는
    별개이고, 2차 적대 리뷰가 그 구분을 짚었다 — 실패한 step은 output을 내지
    않으므로 ``add_output_metadata``로 실은 값은 사라진다. 남는 경로는
    :func:`test_quota_exhaustion_failure_carries_the_spend`가 잰다.
    """

    def _page(page_no: int) -> ProviderPage:
        if page_no == 3:
            raise RuntimeError("upstream 장애")
        return ProviderPage(items=[f"p{page_no}"], total_count=99)

    with counting_upstream_requests() as counter, pytest.raises(RuntimeError):
        list(iter_paginated_items(_page, num_of_rows=1, label="fails"))

    assert counter[0] == 3, "실패로 끝난 요청도 쿼터를 쓴다 — 세야 한다"


def test_quota_exhaustion_failure_carries_the_spend() -> None:
    """쿼터 소진으로 죽을 때 **얼마나 쓰고 죽었는지**가 실패 이벤트에 남는다.

    하필 쿼터 소진이야말로 그 수가 필요한 실패다. output metadata는 실패하면
    사라지지만 ``Failure`` metadata는 실패 이벤트에 붙으므로 남는다.
    """

    class _Exhausted(Exception):
        failure_kind = "quota"

    with counting_upstream_requests():
        note_upstream_request(37)
        with pytest.raises(Failure) as raised:
            raise_terminal_if_quota_exhausted(_Exhausted("일일 한도 초과"))

    metadata = {str(key): value for key, value in (raised.value.metadata or {}).items()}
    assert UPSTREAM_REQUESTS_METADATA_KEY in metadata, (
        "쿼터 소진 Failure가 소비량을 싣지 않았다 — 실패한 step은 output을 내지 "
        "않으므로 이 자리가 아니면 그 수는 사라진다"
    )
    assert "37" in str(metadata[UPSTREAM_REQUESTS_METADATA_KEY])


def test_quota_exhaustion_failure_omits_the_spend_when_nothing_was_counted() -> None:
    """세지 않은 경로가 "0건 쓰고 죽었다"로 보이지 않게 한다."""

    class _Exhausted(Exception):
        failure_kind = "quota"

    with counting_upstream_requests(), pytest.raises(Failure) as raised:
        raise_terminal_if_quota_exhausted(_Exhausted("일일 한도 초과"))

    metadata = {str(key): value for key, value in (raised.value.metadata or {}).items()}
    assert UPSTREAM_REQUESTS_METADATA_KEY not in metadata


# ------------------------------------------------------- metadata까지 닿는가


class _Context:
    """``add_output_metadata``만 갖춘 최소 대역."""

    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}

    def add_output_metadata(self, metadata: dict[str, Any]) -> None:
        self.metadata.update(metadata)


def test_the_choke_point_merges_the_numerator() -> None:
    """``_add_output_metadata``에서 분자가 합쳐진다.

    **feature asset 경로의 초크포인트이고, 이 패키지의 유일한 metadata 자리는
    아니다** — op/sensor/maintenance는 ``context.add_output_metadata``를 직접
    부른다(그쪽은 분자를 스스로 싣는다). feature asset이 그 길로 새는 것은
    ``tests/lint``가 막는다.
    """

    from kortravelmap.dagster.etl import _add_output_metadata

    context = _Context()
    with counting_upstream_requests():
        note_upstream_request(7)
        _add_output_metadata(context, {"provider": "x"})  # type: ignore[arg-type]

    assert context.metadata["provider"] == "x"
    assert context.metadata[UPSTREAM_REQUESTS_METADATA_KEY] == 7


def test_the_choke_point_does_not_overwrite_a_caller_value() -> None:
    """자기 수를 아는 asset이 있으면 그쪽이 더 정확하다."""

    from kortravelmap.dagster.etl import _add_output_metadata

    context = _Context()
    with counting_upstream_requests():
        note_upstream_request(7)
        _add_output_metadata(
            context,
            {UPSTREAM_REQUESTS_METADATA_KEY: 99},  # type: ignore[arg-type]
        )

    assert context.metadata[UPSTREAM_REQUESTS_METADATA_KEY] == 99


def test_the_choke_point_adds_nothing_outside_a_scope() -> None:
    """계수기 밖에서는 key 자체가 없어야 한다 — 0으로 위장하지 않는다."""

    from kortravelmap.dagster.etl import _add_output_metadata

    context = _Context()
    _add_output_metadata(context, {"provider": "x"})  # type: ignore[arg-type]

    assert UPSTREAM_REQUESTS_METADATA_KEY not in context.metadata


def test_the_counter_survives_thread_and_task_boundaries() -> None:
    """문맥이 **복사**되는 경계에서도 계수가 바깥에 보여야 한다.

    `asyncio.to_thread`와 `create_task`는 `contextvars.copy_context()`로 문맥을
    복사한다 — 복사된 것은 매핑이고 **값(리스트 객체)은 같다**. 그래서
    `counter[0] += 1`이 바깥에 보인다. 계수기에 정수를 담았다면 안쪽에서
    `set`이 필요하고 그것은 바깥에 보이지 않아 **조용히 0이 됐을** 자리다.

    이 저장소가 실제로 그 경계를 쓰고, **그 안에서 실제로 센다** —
    `FeatureUpdateAssetRunner`는 계수기를 `asyncio.to_thread(spec.resources, ...)`
    **앞**에서 열고, MOIS Phase A가 바로 그 thread 안에서 전국 파일을 받는다.
    이 성질이 깨지면 그 요청이 통째로 사라진다(2026-09-13 3차 적대 리뷰 blocker).
    """

    def _work() -> None:
        note_upstream_request(5)

    async def _through_thread() -> int:
        with counting_upstream_requests() as counter:
            await asyncio.to_thread(_work)
            return counter[0]

    async def _through_task() -> int:
        with counting_upstream_requests() as counter:
            await asyncio.create_task(asyncio.to_thread(_work))
            return counter[0]

    assert asyncio.run(_through_thread()) == 5
    assert asyncio.run(_through_task()) == 5


# --------------------------------------------------------------------------- #
# 손으로 박은 계수 자리를 **효과로** 결박한다.
#
# `tests/lint/test_every_fetcher_counts_or_declares_why_not.py`는 "자리가 있는가"만
# 본다 — 루프 밖 1회든 도달 불가 분기든 초록이다. 실제로 2026-09-13 2차 적대 리뷰가
# 그 구멍으로 실제 결함 하나를 통과시켰다: `fetch_krheritage_items`가 목록 페이지만
# 세고 record당 1건인 detail을 세지 않았는데, 목록 계수만으로 fetcher가 "센다"로
# 판정됐다. 실린 수는 실제의 약 1%였다.
#
# 그래서 여기서는 **가짜 client로 N번 부르게 하고 계수가 N인지** 잰다. 이것이
# 그 구멍을 막는 유일한 층이다.
# --------------------------------------------------------------------------- #


def _install(monkeypatch: pytest.MonkeyPatch, name: str, **attrs: Any) -> None:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, module)


class _Key:
    def __init__(self, index: int) -> None:
        self.ccba_kdcd = "11"
        self.ccba_asno = f"{index:04d}"
        self.ccba_ctcd = "11"


class _Summary:
    def __init__(self, index: int) -> None:
        self.key = _Key(index)
        self.name_ko = f"item-{index}"


class _Page:
    def __init__(self, items: list[Any], total: int) -> None:
        self.items = items
        self.total = total


async def test_krheritage_items_counts_every_detail_call_not_just_the_list_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """detail은 record당 1 HTTP다 — 목록 페이지만 세면 실린 수가 실제의 1%다.

    2차 적대 리뷰의 blocker를 그대로 재현한 회귀 테스트다. 정적 검사는 이 결함을
    통과시켰다(목록 계수만으로 fetcher가 '센다'로 판정됐다).

    대역은 krheritage native async 표면을 그대로 흉내낸다 — ``search.list``
    (``services/search.py:29``, keyword-only)·``search.details``
    (``services/search.py:70``, ``ccba_*`` 3개 위치인자)·``aclose``
    (``client.py:80``). 이름이나 await 경계가 실물과 어긋나면 계수가 맞아도
    운영은 깨지므로 시그니처까지 결박한다.
    """

    total_items = 250  # 페이지 3장(100/100/50) + detail 250건
    clients: list[_Client] = []

    detail_calls: list[tuple[str, str, str]] = []

    class _Detail:
        """detail 응답 대역 — yield된 것이 이것인지 보기 위해 타입을 준다."""

        def __init__(self, ccba_asno: str) -> None:
            self.ccba_asno = ccba_asno

    class _Search:
        # **catch-all을 두지 않는다.** `**_f`로 받으면 fetcher가 인자 이름을 바꿔도
        # 여기는 초록인데 실물(`krheritage/services/search.py:29`, 전부 keyword-only)은
        # `TypeError`를 낸다. 기본값이 있는 인자일수록 그 구멍이 넓다 — 필수 인자만
        # 우연히 걸린다. 실제 시그니처를 그대로 베낀다.
        async def list(
            self,
            *,
            page_size: int = 100,
            page: int = 1,
            ccba_kdcd: str | None = None,
            ccba_ctcd: str | None = None,
            ccba_asno: str | None = None,
            st_ccba_asdt: str | int | None = None,
            st_ccba_aedt: str | int | None = None,
            ccba_cndt: str | int | None = None,
            ccba_mnm1: str | None = None,
        ) -> _Page:
            del ccba_kdcd, ccba_ctcd, ccba_asno
            del st_ccba_asdt, st_ccba_aedt, ccba_cndt, ccba_mnm1
            start = (page - 1) * page_size
            window = range(start, min(start + page_size, total_items))
            return _Page([_Summary(i) for i in window], total_items)

        async def details(self, ccba_kdcd: str, ccba_asno: str, ccba_ctcd: str) -> object:
            # 호출 인자를 **기록한다.** 그러지 않으면 fetcher가 `await`를 잃어도
            # 여기는 초록이다 — yield되는 것이 코루틴 객체로 바뀌는데 아래 단언이
            # 개수만 보기 때문이다(적대 리뷰 실증: 250건이 코루틴이어도 통과).
            detail_calls.append((ccba_kdcd, ccba_asno, ccba_ctcd))
            return _Detail(ccba_asno)

    class _Client:
        def __init__(self, **_kwargs: Any) -> None:
            self.search = _Search()
            self.closed = False
            clients.append(self)

        async def aclose(self) -> None:
            self.closed = True

    _install(monkeypatch, "krheritage", HeritageClient=_Client)
    settings = KorTravelMapSettings(
        data_go_kr_service_key=SecretStr("k"), krheritage_kind_codes="11"
    )

    with counting_upstream_requests():
        records = [record async for record in fetch_krheritage_items(settings)]
        observed = observed_upstream_requests()

    assert len(records) == total_items
    # **무엇이 yield됐는지**를 본다. 개수만 보면 `await`가 빠져 코루틴 객체가
    # 흘러나가도 통과한다.
    assert all(isinstance(record, _Detail) for record in records), (
        "detail이 아닌 것이 yield됐다 — `await`가 빠지면 코루틴 객체가 그대로 나간다"
    )
    assert len(detail_calls) == total_items
    assert detail_calls[0] == ("11", "0000", "11"), (
        f"detail 인자 순서가 {detail_calls[0]}다 — 실물은 "
        "`details(ccba_kdcd, ccba_asno, ccba_ctcd)` 위치 인자다"
    )
    assert observed == 3 + total_items, (
        f"목록 3페이지 + detail {total_items}건 = {3 + total_items}건인데 "
        f"{observed}건을 셌다. 목록만 세면 3이 나온다 — 실제의 1%다."
    )
    assert [client.closed for client in clients] == [True], (
        "fetcher가 client를 닫지 않았다 — `finally`의 정리 메서드 이름이 실물"
        "(`HeritageClient.aclose`)과 어긋나면 세션이 샌다"
    )


async def test_datagokr_file_data_counts_one_request_per_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``iter_all``은 provider 안에서 페이지를 돌아 셀 수 없었다. ``iter_pages``는 센다.

    실물 ``file_data.iter_pages``는 dataset을 위치인자로 받는 async generator이고
    (``datagokr/services/file_data.py:158``) 정리는 ``aclose``
    (``datagokr/client.py:179``)다.
    """

    pages = [[object(), object()], [object(), object()], [object()]]
    clients: list[_Client] = []

    class _FileData:
        def __init__(self) -> None:
            self.datasets: list[str] = []

        async def iter_pages(self, dataset: str, **_kwargs: Any) -> AsyncIterator[Any]:
            self.datasets.append(dataset)
            for items in pages:
                yield SimpleNamespace(items=list(items))

    class _Client:
        def __init__(self, **_kwargs: Any) -> None:
            self.file_data = _FileData()
            self.closed = False
            clients.append(self)

        async def aclose(self) -> None:
            self.closed = True

    _install(monkeypatch, "datagokr", DataGoKrClient=_Client)
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("k"))

    with counting_upstream_requests():
        records = [
            record
            async for record in fetch_datagokr_file_data_records(
                settings, dataset_key="ds"
            )
        ]
        observed = observed_upstream_requests()

    assert len(records) == 5
    assert observed == len(pages), (
        f"페이지 {len(pages)}장인데 {observed}건을 셌다 — 페이지마다 HTTP 1건이다"
    )
    assert len(clients) == 1
    assert clients[0].file_data.datasets == ["ds"]
    assert clients[0].closed is True, (
        "fetcher가 client를 닫지 않았다 — 정리 메서드 이름이 실물"
        "(`DataGoKrClient.aclose`)과 어긋났다"
    )


async def test_krheritage_events_counts_every_month_including_the_empty_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """빈 달도 요청 1건을 쓴다 — record 수로는 역산되지 않는다.

    ``event.by_month``는 실물에서 keyword-only async다
    (``services/event.py:21``) — 대역도 같아야 계수가 아니라 **호출 모양**까지
    결박된다.
    """

    clients: list[_Client] = []

    class _Event:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int]] = []

        async def by_month(self, *, year: int, month: int) -> tuple[object, ...]:
            self.calls.append((year, month))
            return (object(),) if len(self.calls) == 1 else ()

    class _Client:
        def __init__(self, **_kwargs: Any) -> None:
            self.event = _Event()
            self.closed = False
            clients.append(self)

        async def aclose(self) -> None:
            self.closed = True

    _install(monkeypatch, "krheritage", HeritageClient=_Client)
    settings = KorTravelMapSettings(data_go_kr_service_key=SecretStr("k"))

    with counting_upstream_requests():
        records = [record async for record in fetch_krheritage_events(settings)]
        observed = observed_upstream_requests()

    assert len(records) == 1
    assert observed == 14, (
        f"record는 1건이지만 요청은 14건(달마다 1건)이다 — {observed}건을 셌다"
    )
    assert len(clients) == 1
    assert len(clients[0].event.calls) == 14, (
        "센 수와 실제로 부른 달 수가 갈라졌다 — 계수기가 호출과 무관해진 것이다"
    )
    assert clients[0].closed is True, (
        "fetcher가 client를 닫지 않았다 — 정리 메서드 이름이 실물"
        "(`HeritageClient.aclose`)과 어긋났다"
    )


def test_the_opinet_budget_counts_exactly_the_calls_it_allows() -> None:
    """OpiNet 예산기가 곧 분자다 — 예산이 끊은 호출은 나가지 않으므로 세지 않는다."""

    with counting_upstream_requests():
        budget = _OpinetCallBudget(3)
        allowed = [budget.spend() for _ in range(5)]
        observed = observed_upstream_requests()

    assert allowed == [True, True, True, False, False]
    assert observed == 3, f"허용된 3건만 세야 하는데 {observed}건을 셌다"


def test_the_unbounded_opinet_budget_still_counts() -> None:
    """예산이 없는 경로(`_unbounded`)도 요청은 나간다 — 세지 않으면 0으로 위장한다."""

    with counting_upstream_requests():
        budget = _OpinetCallBudget(None)
        for _ in range(4):
            assert budget.spend() is True
        observed = observed_upstream_requests()

    assert observed == 4


async def test_opinet_price_details_counts_every_station_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """bbox 모드의 상세 조회는 uni_id마다 1건이다 — 규모가 큰 자리라 효과로 잰다.

    enumerate(`iter_stations_in_bbox`)는 provider가 격자 셀마다 부르므로 이 층에서
    셀 수 없다(`_PARTIALLY_COUNTED`). 셀 수 있는 절반은 정확한지 여기서 결박한다.

    대역은 실물 표면을 **인자 이름까지** 흉내낸다 — ``iter_stations_in_bbox``는
    keyword-only async generator 함수이고(``opinet/client.py:548``) 호출 자체는
    await하지 않는다, ``get_station_detail``은 await 대상
    (``opinet/client.py:513``), 정리는 ``aclose``(``opinet/client.py:321``)다.
    ``**_kwargs``로 받아 버리면 fetcher가 인자 이름을 바꿔도 초록이라 그 구멍을
    닫는다. **필수 인자만으로는 부족하다** — 기본값이 있는 인자(`radius_m`)를
    `radius`로 바꾸는 변이가 catch-all 아래에서 초록이었고, 실물은 `TypeError`를
    낸 뒤 조용히 기본 5000m로 떨어졌을 자리다(적대 리뷰 실증). 그래서 기록한
    bbox 튜플을 값까지 단언한다.
    """

    stations = [SimpleNamespace(uni_id=f"S{index:03d}") for index in range(7)]

    class _Client:
        def __init__(self, **_kwargs: Any) -> None:
            self.details: list[str] = []
            self.bboxes: list[tuple[float, float, float, float, int]] = []
            self.closed = False

        async def iter_stations_in_bbox(
            self,
            *,
            min_lon: float,
            min_lat: float,
            max_lon: float,
            max_lat: float,
            radius_m: int = 5000,
            prodcd: Any = None,
            sort: Any = None,
        ) -> AsyncIterator[Any]:
            del prodcd, sort
            self.bboxes.append((min_lon, min_lat, max_lon, max_lat, radius_m))
            for station in stations:
                yield station

        async def get_station_detail(self, uni_id: str) -> object:
            self.details.append(uni_id)
            return SimpleNamespace(uni_id=uni_id)

        async def aclose(self) -> None:
            self.closed = True

    client = _Client()
    _install(monkeypatch, "opinet", OpinetClient=lambda **kwargs: client)
    settings = KorTravelMapSettings(
        opinet_api_key=SecretStr("k"),
        opinet_scope_mode="bbox",
        opinet_scope_bbox="126.9,37.5,127.0,37.6",
    )

    with counting_upstream_requests():
        records = [
            record async for record in fetch_opinet_station_price_details(settings)
        ]
        observed = observed_upstream_requests()

    assert len(records) == len(stations)
    assert observed == len(stations), (
        f"uni_id {len(stations)}개의 상세를 부르고 {observed}건을 셌다 — "
        "상세는 uni_id마다 정확히 1건이다"
    )
    assert client.details == [station.uni_id for station in stations], (
        "센 수와 실제로 부른 uni_id가 갈라졌다 — 계수기가 호출과 무관해진 것이다"
    )
    # **값까지 본다.** 개수만 보면 `radius_m=`를 `radius=`로 바꾸는 변이가 통과하고
    # (실물은 `TypeError`), settings의 bbox/반경이 실제로 도달하는지도 모른 채 지나간다.
    assert client.bboxes == [(126.9, 37.5, 127.0, 37.6, settings.opinet_scope_radius_m)], (
        f"enumerate에 도달한 인자가 {client.bboxes}다 — bbox 1개짜리 scope의 "
        "좌표와 반경이 그대로 실려야 한다"
    )
    assert client.closed is True, (
        "fetcher가 client를 닫지 않았다 — 정리 메서드 이름이 실물"
        "(`OpinetClient.aclose`)과 어긋났다"
    )
