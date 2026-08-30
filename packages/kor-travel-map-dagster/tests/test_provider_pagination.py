"""``provider_pagination`` 종료 규칙 테스트.

이 모듈이 존재하는 이유는 provider가 응답 행을 조용히 걸러 낼 수 있기 때문이다.
그래서 테스트도 "정상 경로가 동작하는가"가 아니라 **"걸러 낸 상황에서 무엇을
하는가"** 를 본다.
"""

from __future__ import annotations

import pytest

from kortravelmap.dagster.provider_pagination import (
    DEFAULT_MAX_PAGES,
    ProviderPage,
    ProviderPaginationOverrun,
    iter_paginated_items,
)


class _Upstream:
    """page_no → 행 수를 흉내 내는 최소 upstream."""

    def __init__(
        self,
        pages: dict[int, int],
        *,
        total_count: int | None,
        raise_after: type[BaseException] | None = None,
    ) -> None:
        self.pages = pages
        self.total_count = total_count
        self.raise_after = raise_after
        self.requested: list[int] = []

    def __call__(self, page_no: int) -> ProviderPage:
        self.requested.append(page_no)
        if page_no not in self.pages:
            if self.raise_after is not None:
                raise self.raise_after("no more data")
            return ProviderPage(items=[], total_count=self.total_count)
        rows = [f"p{page_no}-{i}" for i in range(self.pages[page_no])]
        return ProviderPage(items=rows, total_count=self.total_count)


class _NoMoreData(Exception):
    """provider가 "더 없음"을 예외로 알리는 경우 (krex/airkorea 형태)."""


def _run(upstream: _Upstream, **kwargs: object) -> tuple[list[object], list[str]]:
    warnings: list[str] = []
    items = list(
        iter_paginated_items(
            upstream,
            num_of_rows=kwargs.pop("num_of_rows", 1000),  # type: ignore[arg-type]
            label="test",
            warn=warnings.append,
            **kwargs,  # type: ignore[arg-type]
        )
    )
    return items, warnings


def test_short_page_does_not_end_pagination_when_more_is_declared() -> None:
    """**이 모듈의 존재 이유.** provider가 행 하나를 걸러도 절단되지 않아야 한다.

    krex ``_parse_page``가 파싱 실패 행을 건너뛰게 되면서 1000행 만재 페이지가
    999로 온다. 종전 관용구는 그것을 마지막 페이지로 읽고 나머지를 조용히 버렸다.
    """
    upstream = _Upstream({1: 999, 2: 1000, 3: 501}, total_count=2500)
    items, warnings = _run(upstream)

    assert len(items) == 2500
    assert upstream.requested == [1, 2, 3]
    assert len(warnings) == 1
    assert "999/1000" in warnings[0]


def test_exact_completion_emits_no_warning() -> None:
    """정상 경로에서는 경고가 없어야 한다 — 경고가 흔하면 신호가 아니다."""
    upstream = _Upstream({1: 1000, 2: 500}, total_count=1500)
    items, warnings = _run(upstream)

    assert len(items) == 1500
    assert warnings == []


def test_short_page_ends_pagination_when_total_is_unknown() -> None:
    """``total_count``가 없으면 짧은 페이지 외에 판정 근거가 없다."""
    upstream = _Upstream({1: 1000, 2: 3}, total_count=None)
    items, warnings = _run(upstream)

    assert len(items) == 1003
    assert upstream.requested == [1, 2]
    assert warnings == []


def test_non_positive_total_count_is_treated_as_unknown() -> None:
    """khoa ``Page.total_count``는 ``int = 0``이라 미제공과 0을 구분하지 못한다.

    0을 권위로 믿으면 만재 페이지를 받고도 ``seen >= 0``이 참이라 첫 페이지에서
    종료한다 — 고치려는 절단보다 나쁘다.
    """
    upstream = _Upstream({1: 1000, 2: 10}, total_count=0)
    items, _ = _run(upstream)

    assert len(items) == 1010
    assert upstream.requested == [1, 2]


def test_upstream_delivering_less_than_declared_is_reported() -> None:
    """선언보다 적게 주고 페이지가 비면 누락이 드러나야 한다."""
    upstream = _Upstream({1: 1000}, total_count=5000)
    items, warnings = _run(upstream)

    assert len(items) == 1000
    assert len(warnings) == 1
    assert "5000" in warnings[0]
    assert "1000" in warnings[0]


def test_end_of_pages_exception_terminates_cleanly() -> None:
    """빈 페이지 대신 예외로 끝을 알리는 provider를 정상 종료로 받는다.

    krex는 resultCode ``03``/``NO_DATA``에 ``KrexNotFoundError``를, airkorea는
    ``AirKoreaNoDataError``를 던진다. 이 훅이 없으면 "짧은 페이지에서 계속" 규칙이
    마지막 페이지 다음 요청을 만들어 asset을 실패시킨다.
    """
    upstream = _Upstream({1: 999, 2: 1000}, total_count=2500, raise_after=_NoMoreData)
    items, warnings = _run(upstream, end_of_pages=(_NoMoreData,))

    assert len(items) == 1999
    assert upstream.requested == [1, 2, 3]
    # 짧은 페이지 경고 + 선언 미달 종료 경고
    assert len(warnings) == 2
    assert "페이지 종료를 알렸다" in warnings[-1]


def test_end_of_pages_exception_propagates_when_not_declared() -> None:
    """선언하지 않은 예외는 잡지 않는다 — 조용히 삼키면 절단이 된다."""
    upstream = _Upstream({1: 1000}, total_count=5000, raise_after=_NoMoreData)

    with pytest.raises(_NoMoreData):
        _run(upstream)


def test_page_ceiling_is_derived_from_declared_total() -> None:
    """상한은 선언 건수에서 유도하고, 닿으면 조용히 자르지 않고 실패한다.

    provider가 행을 과도하게 걸러 내면 "짧은 페이지에서 계속" 규칙이 영원히 끝나지
    않을 수 있다. 선언 1,000건 / 100행이면 10 페이지면 충분한데 매 페이지가 1건만
    주므로 절대 도달하지 못한다 — 유도 상한(10 × 2 + 1 = 21)에서 멈춰야 한다.
    ``max_pages``를 크게 줘도 **유도 상한이 더 작으면 그쪽이 이기지 않는다**는 것도
    함께 본다(둘 중 큰 쪽을 쓴다).
    """
    calls: list[int] = []

    def starving(page_no: int) -> ProviderPage:
        calls.append(page_no)
        return ProviderPage(items=["x"], total_count=1_000)

    with pytest.raises(ProviderPaginationOverrun) as excinfo:
        list(
            iter_paginated_items(
                starving,
                num_of_rows=100,
                label="starving",
                max_pages=21,
            )
        )
    assert "상한" in str(excinfo.value)
    assert len(calls) == 21, f"상한 21에서 멈춰야 한다 (실제 {len(calls)})"


def test_unknown_total_uses_the_conservative_default_ceiling() -> None:
    """``total_count``를 모르면 전역 상한이 그대로 걸린다.

    Dagster ``max_runtime``(7,200초)보다 먼저 걸려야 "시끄럽게 실패한다"는 설계가
    성립한다 — 전역 10,000은 그러지 못했다.
    """

    def never_short(page_no: int) -> ProviderPage:
        return ProviderPage(items=["x"] * 100, total_count=None)

    with pytest.raises(ProviderPaginationOverrun):
        list(iter_paginated_items(never_short, num_of_rows=100, label="endless"))
    assert DEFAULT_MAX_PAGES <= 1000, "상한이 run 시간 안에 도달 가능해야 한다"


def test_empty_first_page_stops_without_warning() -> None:
    """빈 결과는 정상이다 — 선언 건수가 없으면 경고하지 않는다."""
    upstream = _Upstream({}, total_count=None)
    items, warnings = _run(upstream)

    assert items == []
    assert warnings == []


def test_items_are_yielded_lazily() -> None:
    """generator 계약 — 소비한 만큼만 요청해야 한다.

    호출부가 ``yield from``으로 감싸므로, 소비자가 중간에 멈추면 뒤 페이지를
    요청하지 않아야 한다(쿼터 보호).
    """
    upstream = _Upstream({1: 1000, 2: 1000, 3: 500}, total_count=2500)
    stream = iter_paginated_items(upstream, num_of_rows=1000, label="lazy")

    first = next(stream)

    assert first == "p1-0"
    assert upstream.requested == [1]
    stream.close()
    assert upstream.requested == [1]
