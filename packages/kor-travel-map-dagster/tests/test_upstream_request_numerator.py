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
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

from kortravelmap.dagster.provider_pagination import (
    ProviderPage,
    aiter_paginated_items,
    iter_paginated_items,
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
    "0번 요청했다"고 보고했다 — 하필 분모를 실측한 유일한 provider(OpiNet)가
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


def test_a_failed_sweep_still_reports_what_it_spent() -> None:
    """실패한 run이 쿼터를 얼마나 썼는지가 사후 판독의 값이다."""

    def _page(page_no: int) -> ProviderPage:
        if page_no == 3:
            raise RuntimeError("upstream 장애")
        return ProviderPage(items=[f"p{page_no}"], total_count=99)

    with counting_upstream_requests() as counter, pytest.raises(RuntimeError):
        list(iter_paginated_items(_page, num_of_rows=1, label="fails"))

    assert counter[0] == 3, "실패로 끝난 요청도 쿼터를 쓴다 — 세야 한다"


# ------------------------------------------------------- metadata까지 닿는가


class _Context:
    """``add_output_metadata``만 갖춘 최소 대역."""

    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}

    def add_output_metadata(self, metadata: dict[str, Any]) -> None:
        self.metadata.update(metadata)


def test_the_choke_point_merges_the_numerator() -> None:
    """``_add_output_metadata``가 유일한 초크포인트다 — 여기서 합쳐진다."""

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

    이 저장소가 실제로 그 경계를 쓴다(`feature_update_runner`의
    `asyncio.to_thread(spec.resources, ...)`). 지금은 그쪽이 계수기를 열지 않지만,
    asset 경로가 thread로 옮겨가는 날 이 성질이 조용히 깨지면 안 된다.
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
