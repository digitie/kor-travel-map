"""``provider_pagination`` 종료 규칙 테스트.

이 모듈이 존재하는 이유는 provider가 응답 행을 조용히 걸러 낼 수 있기 때문이다.
그래서 테스트도 "정상 경로가 동작하는가"가 아니라 **"걸러 낸 상황에서 무엇을
하는가"** 를 본다.
"""

from __future__ import annotations

import pytest

from kortravelmap.dagster.provider_pagination import (
    DEFAULT_ABSOLUTE_MAX_PAGES,
    DEFAULT_MAX_PAGES,
    ProviderPage,
    ProviderPaginationOverrun,
    ProviderPaginationStalled,
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


def test_declared_total_raises_the_ceiling_but_not_past_the_absolute_one() -> None:
    """**``max_pages``는 천장이 아니라 바닥이다.** 그 위에 천장이 있어야 한다.

    ``absorb``가 선언 건수에 맞춰 ``ceiling``을 올리는 설계는 옳다 — 선언 건수가
    상한을 정한다. 그러나 그 위에 아무것도 없으면 **upstream이 말한 숫자가 곧
    우리의 요청 수**가 된다. ``total_count``를 잘못 파싱하거나 upstream이 거짓을
    말하면 한 번의 sweep이 쿼터를 통째로 태운다.

    2026-09-13에 이것을 값을 치르고 배웠다. krforest 호출 4곳에 ``max_pages=10``을
    주고 "묶었다"고 적었는데, 선언 건수를 크게 둔 테스트가 상한을 무시하고 계속
    걸었다.
    """

    calls: list[int] = []

    def endless_with_huge_declared_total(page_no: int) -> ProviderPage:
        calls.append(page_no)
        return ProviderPage(items=[f"p{page_no}"], total_count=10**9)

    with pytest.raises(ProviderPaginationOverrun) as caught:
        list(
            iter_paginated_items(
                endless_with_huge_declared_total,
                num_of_rows=1,
                label="huge-declared",
                max_pages=5,
                absolute_max_pages=5,
            )
        )

    assert len(calls) == 5, f"절대 상한을 넘겨 {len(calls)}페이지를 걸었다"
    assert "절대 상한" in str(caught.value), (
        "실패 문구가 어느 상한에 걸렸는지 말하지 않으면 운영자가 잘못된 값을 고친다"
    )


def test_max_pages_alone_does_not_bound_a_lying_upstream() -> None:
    """회귀 표식 — 절대 상한을 빼면 ``max_pages``만으로는 묶이지 않는다.

    이 테스트는 결함의 **모양**을 박아 둔다. ``absolute_max_pages``를 크게 두면
    ``max_pages=5``는 upstream의 선언에 밀려 아무것도 막지 못한다.
    """

    calls: list[int] = []

    def finite_but_long(page_no: int) -> ProviderPage:
        calls.append(page_no)
        if page_no > 40:
            return ProviderPage(items=[], total_count=10**9)
        return ProviderPage(items=[f"p{page_no}"], total_count=10**9)

    list(
        iter_paginated_items(
            finite_but_long,
            num_of_rows=1,
            label="lying-upstream",
            max_pages=5,
            absolute_max_pages=DEFAULT_ABSOLUTE_MAX_PAGES,
        )
    )

    assert len(calls) > 5, (
        "`max_pages`가 천장처럼 동작했다 — 이 테스트가 박아 둔 사실이 바뀌었다면 "
        "`absorb`의 상한 상향 규칙을 다시 읽어라."
    )


def test_a_stalled_upstream_is_caught_not_absorbed() -> None:
    """``page_no``를 무시하는 upstream을 조용히 흡수하지 않는다.

    같은 100건을 30번 받고 "3,000건 수집"으로 끝나는 모양이다 — 중복은 upsert가
    흡수하므로 run은 초록이고 누락은 보이지 않는다. 이 검사는 원래 provider
    라이브러리에 있었고(visitkorea `iter_paginated_pages`), 쿼터 상한을 얻으려
    저장소 헬퍼로 옮기면서 잃었다가 적대 리뷰에 잡혀 되살렸다.
    """

    calls: list[int] = []

    def never_advances(page_no: int) -> ProviderPage:
        calls.append(page_no)
        return ProviderPage(
            items=["a", "b"], total_count=3000, fingerprint={"body": "same"}
        )

    with pytest.raises(ProviderPaginationStalled):
        list(
            iter_paginated_items(
                never_advances, num_of_rows=2, label="stalled", max_pages=50
            )
        )
    assert calls == [1, 2], f"두 번째 페이지에서 멈춰야 한다 — {len(calls)}번 걸었다"


def test_a_fingerprint_that_actually_changes_is_not_flagged() -> None:
    """항진명제 방지 — 전진하는 upstream은 통과해야 한다."""

    def advances(page_no: int) -> ProviderPage:
        return ProviderPage(
            items=[f"p{page_no}"] if page_no <= 3 else [],
            total_count=3,
            fingerprint={"page": page_no},
        )

    assert list(iter_paginated_items(advances, num_of_rows=1, label="ok")) == [
        "p1",
        "p2",
        "p3",
    ]


def test_a_synthesized_total_count_is_at_least_audible() -> None:
    """provider가 ``totalCount``를 ``len(items)``로 채우면 조용히 잘린다 — 들리게 한다.

    2026-09-13 실측: 2,500행 dataset에서 이 헬퍼도 1,000행만 받고 끝났다. 즉
    라이브러리 iterator에서 저장소 헬퍼로 옮긴 것이 이 절단을 **고치지 않는다**.
    종료 규칙 자체를 바꾸면 범위 밖 page에 예외를 던지는 provider에서 새 실패가
    생기므로, 여기서는 경고만 낸다 — 적대 리뷰가 이 자리의 근거가 거꾸로였다고
    지적한 뒤 실측으로 확인한 결과다.
    """

    warnings: list[str] = []
    page_size = 1000
    total = 2500

    def synthesized(page_no: int) -> ProviderPage:
        start = (page_no - 1) * page_size
        items = list(range(start, min(start + page_size, total)))
        # upstream이 totalCount를 안 주면 lib이 len(items)로 채운다.
        return ProviderPage(items=items, total_count=len(items))

    collected = list(
        iter_paginated_items(
            synthesized,
            num_of_rows=page_size,
            label="synthesized-total",
            warn=warnings.append,
        )
    )

    assert len(collected) == page_size, (
        "종료 규칙이 바뀌었다 — 바꿨다면 범위 밖 page 예외를 던지는 provider를 "
        "먼저 확인하고 이 테스트를 갱신해라."
    )
    assert warnings, "조용히 잘렸다 — 경고가 없으면 아무도 알아차리지 못한다"
    assert "totalCount" in warnings[0]
