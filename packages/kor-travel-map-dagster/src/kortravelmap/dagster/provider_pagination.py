"""provider 페이지네이션 종료 조건 (조용한 절단 방지).

## 왜 필요한가

data.go.kr 계열 provider 페이지네이션은 본 저장소 6곳에서 같은 관용구를 썼다::

    items = fetch(page_no)
    if not items:
        break
    yield from items
    if len(items) < num_of_rows:   # <-- 마지막 페이지 판정
        break
    page_no += 1

이 관용구는 **"비어 있지 않은 짧은 페이지 = 마지막 페이지"** 를 가정한다. 그 가정은
provider가 응답 행을 그대로 돌려줄 때만 성립한다.

python-krex-api ``ddd69cd2 → c6d8717e``의 ``_parse_page``가 "행 하나라도 파싱 실패하면
``KrexParseError``"에서 "실패 행은 건너뛰고 전 행 실패일 때만 raise"로 바뀌면서 그
가정이 깨졌다. 1000행 만재 페이지에서 1행만 파싱 실패해도 ``items``가 999가 되고,
위 관용구는 그것을 마지막 페이지로 읽어 **나머지 데이터셋 전체를 조용히 버린다.**
로그도 예외도 남지 않는다.

## 종료 규칙

``total_count``가 권위이고, 짧은 페이지는 ``total_count``가 없을 때만 쓰는 **대체
휴리스틱**이다.

===========================  ===================  ==========================
상태                          total_count 있음      total_count 없음
===========================  ===================  ==========================
빈 페이지                      종료                  종료
``seen >= total_count``       종료                  (판정 불가)
짧은 페이지, seen < total      **계속 + 경고**        종료
``page_no > 상한``            예외                  예외
"더 없음" 예외                 종료(+경고)            종료
===========================  ===================  ==========================

마지막 줄이 ``end_of_pages``다. 빈 페이지 대신 **예외로** 끝을 알리는 provider가 있다 —
krex는 resultCode ``03``/``NO_DATA``에 ``KrexNotFoundError``를, airkorea는
``AirKoreaNoDataError``를 던진다. 두 라이브러리 모두 자기 내부 페이지네이션에서 그
예외를 종료로 잡는다. 이 훅이 없으면 "짧은 페이지에서 계속 진행" 규칙이 마지막 페이지
다음 요청을 만들어 asset을 실패시킨다(적대 리뷰).

"짧은 페이지인데 아직 다 못 받았다"에서 계속 진행하는 것이 이번 보정의 본체다.
그리고 그 상황은 **반드시 경고로 드러난다** — provider가 행을 걸렀다는 유일한 신호이기
때문이다. 조용히 넘어가면 고치기 전과 같아진다.

상한 초과는 조용히 자르지 않고 예외로 올린다. 조용한 상한은 "전부 받았다"로 읽히는
절단이고, 그것이 애초의 문제다.
"""

from __future__ import annotations

from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Iterator,
    Sequence,
)
from dataclasses import dataclass
from typing import Any, Final

DEFAULT_MAX_PAGES: Final = 200
"""``total_count``를 모를 때의 페이지 상한.

무한 루프 방지용 안전장치이지 정상 종료 조건이 아니다. page_no가 범위를 넘으면
upstream이 빈 페이지를 주거나 "더 없음" 예외를 던지는 것이 정상이고, 그러지 않고
마지막 페이지를 반복해 주는 upstream에서 루프가 갇히지 않게 한다.

**전역 10,000은 상한 구실을 하지 못한다**(적대 리뷰). Dagster job의
``dagster/max_runtime``은 7,200초이고 요청당 0.3~1초이므로, 10,000 페이지에 도달하기
훨씬 전에 run monitoring이 run을 죽인다 — 즉 "시끄럽게 실패한다"는 설계 목표가
달성되지 않는다. data.go.kr 일일 쿼터도 그 전에 소진된다. 100 rows/page 기준 2만 건인
200으로 낮추고, ``total_count``를 아는 경로는 아래처럼 선언 건수에서 유도한다.

**요청당 0.3~1초은 쿼터 안에서 도는 구간의 값이다.** 형제 저장소가 2026-09-12에
측정한 바로는 무료 티어를 초과해 throttle되면 요청당 12~17초가 된다(40~50배). 200
페이지 × 15초 ≈ 3,000초이므로 이 상한은 그 구간에서도 7,200초 안이다 — 즉 위 논증은
throttle 구간에서도 성립한다. 다만 어느 구간을 가정했는지 적지 않으면 다음 사람이
상한을 올릴 때 그 배수를 잊는다.
"""

DEFAULT_ABSOLUTE_MAX_PAGES: Final = 10_000
"""**선언 건수가 넘지 못하는** 절대 상한.

``max_pages``는 상한이 아니라 **바닥**이다. ``absorb``가
``ceiling = max(ceiling, needed * _DECLARED_PAGE_SLACK + 1)``로 선언 건수에 맞춰
올리기 때문이다 — 그 설계는 옳다(선언 건수가 상한을 정한다). 그런데 그 위에
아무것도 없으면 **upstream이 말한 숫자가 곧 우리의 요청 수**가 된다.
``total_count``를 잘못 파싱하거나 upstream이 거짓을 말하면 그 한 번의 sweep이
쿼터를 통째로 태운다.

2026-09-13에 그것이 실측으로 드러났다. krforest 4곳을 이 헬퍼로 옮기며
``max_pages=10``을 주고 "이제 묶였다"고 적었는데, 선언 건수를 10억으로 둔 테스트가
1,000페이지를 전부 걸었다. **바닥을 낮춘 것이 천장을 낮춘 것이 아니었다.**

기본값 10,000은 provider 라이브러리들이 스스로 두는 hard cap과 같은 크기다
(``krforest._ITER_PAGES_HARD_PAGE_CAP``). 여기서 그것을 좁히지 않는 이유는 기존
호출자(MOIS bulk 등)의 정상 동작을 바꾸지 않기 위해서다 — 이 기본값이 닫는 것은
"무한"이지 "많음"이 아니다. 쿼터가 좁은 경계는 호출 지점에서
``absolute_max_pages``를 명시해 따로 좁힌다.
"""

_DECLARED_PAGE_SLACK: Final = 2
"""``total_count``를 알 때 허용하는 여유 배수.

provider가 행을 걸러 낼 수 있으므로 ``ceil(declared / num_of_rows)``보다 많은 페이지가
정상적으로 필요할 수 있다. 그러나 무한정은 아니다 — 절반이 걸러지는 상황이면 상한에
걸려 시끄럽게 실패하는 편이 낫다.
"""


class ProviderPaginationOverrun(RuntimeError):
    """페이지 상한을 넘겼다 — 조용히 자르지 않고 실패시킨다."""


class ProviderPaginationStalled(RuntimeError):
    """``page_no``를 올렸는데 upstream이 **같은 페이지**를 다시 줬다.

    ``pageNo``를 무시하는 upstream이 있다. 그때 선언 건수만 믿고 걷으면 같은 100건을
    30번 받고도 "3,000건 수집"으로 끝난다 — 중복은 upsert가 흡수하므로 run은 초록이고
    누락은 보이지 않는다.

    이 검사는 원래 provider 라이브러리 쪽에 있었다(``visitkorea``의
    ``iter_paginated_pages``가 직전 ``page.raw``와 비교해 ``TourApiParseError``를
    던진다). 2026-09-13에 쿼터 상한을 얻으려 저장소 헬퍼로 옮기면서 그 능력을 잃었고,
    적대 리뷰가 그것을 잡았다. 여기서 되살리되 provider에 매이지 않는 형태로 둔다 —
    호출자가 :attr:`ProviderPage.fingerprint`를 주면 켜진다.
    """


@dataclass(frozen=True, slots=True)
class ProviderPage:
    """provider 1페이지의 종료 판정에 필요한 최소 정보.

    ``total_count``는 upstream이 선언한 전체 건수다. 알 수 없으면 ``None``이고,
    그때만 짧은 페이지 휴리스틱으로 되돌아간다.
    """

    items: Sequence[Any]
    total_count: int | None = None
    fingerprint: Any = None
    """이 페이지를 식별하는 값(보통 provider raw body). 주면 전진 검사가 켜진다.

    ``None``이면 검사하지 않는다 — 모든 provider가 비교 가능한 raw를 주지는 않기
    때문이다. 값이 있으면 직전 페이지와 ``==``로 비교한다.
    """

    @property
    def declared_total(self) -> int | None:
        """권위로 쓸 수 있는 전체 건수. 쓸 수 없으면 ``None``.

        **0 이하는 "없음"으로 본다.** provider마다 미제공 표현이 다르기 때문이다 —
        krex ``Page.total_count``는 ``int | None = None``이지만 khoa ``Page.
        total_count``는 ``int = 0``이다. 0을 권위로 믿으면 만재 페이지를 받고도
        ``seen >= 0``이 참이라 첫 페이지에서 종료해 버린다. 그것은 고치려는 절단보다
        더 나쁘다.
        """
        if self.total_count is None or self.total_count <= 0:
            return None
        return self.total_count


def iter_paginated_items(
    fetch_page: Callable[[int], ProviderPage],
    *,
    num_of_rows: int,
    label: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    absolute_max_pages: int = DEFAULT_ABSOLUTE_MAX_PAGES,
    end_of_pages: tuple[type[BaseException], ...] = (),
    first_page_end_of_pages_is_failure: bool = False,
    warn: Callable[[str], None] | None = None,
) -> Iterator[Any]:
    """``fetch_page(page_no)``를 소진하며 item을 lazily yield한다.

    Parameters
    ----------
    fetch_page:
        1-based page 번호를 받아 :class:`ProviderPage`를 돌려준다. 재시도 경계가
        필요하면 호출자가 이 콜러블 **안에서** 감싼다.
    num_of_rows:
        요청한 페이지 크기. 짧은 페이지 판정에만 쓴다.
    label:
        경고 문구에 넣을 호출 경계 이름 (예: ``"krex restarea.list_all"``).
    max_pages:
        ``total_count``를 모를 때의 안전 상한. 넘기면
        :class:`ProviderPaginationOverrun`. 아는 경우에는
        ``ceil(total_count / num_of_rows) * _DECLARED_PAGE_SLACK + 1``과 이 값 중
        **큰 쪽**을 쓴다 — 선언 건수가 상한을 정하게 한다. 즉 이것은 천장이 아니라
        **바닥**이다.
    absolute_max_pages:
        선언 건수가 **넘지 못하는** 천장. upstream이 ``total_count``를 거짓으로
        크게 말하거나 provider가 그것을 잘못 파싱하면 위 규칙만으로는 요청 수가
        upstream의 숫자를 따라간다 — 쿼터가 좁은 경계에서는 그 한 번이 하루치를
        태운다. 기본값은 :data:`DEFAULT_ABSOLUTE_MAX_PAGES`.
    first_page_end_of_pages_is_failure:
        ``end_of_pages``가 **첫 페이지에서** 올라왔을 때 정상 종료로 삼키지 않고
        다시 던진다. 기본값 ``False``는 "데이터가 하나도 없는 것이 정상 상태"인
        경계용이다(예: 현재 진행 중인 교통 공지 0건).

        **authoritative snapshot을 적재하는 경계는 반드시 ``True``로 준다.** 거기서
        0행은 "없음"이 아니라 "못 받았음"일 수 있고, ``retire_absent_from_snapshot``이
        켜진 적재는 빈 snapshot을 받으면 그 source의 feature를 **전부 은퇴**시킨다
        (``feature_repo.retire_features_absent_from_snapshot``). 2026-09-13 적대
        리뷰가 이 구멍을 잡았다 — krforest 4개 fetcher를 이 헬퍼로 옮기며
        ``end_of_pages``를 달았는데, 그것이 종전의 시끄러운 실패를 조용한 0행
        성공으로 바꿨다.
    end_of_pages:
        "더 이상 페이지가 없다"를 **예외로 알리는** provider의 예외형들. 빈 페이지
        대신 예외를 던지는 provider가 있다 — krex는 resultCode ``03``/``NO_DATA``에
        ``KrexNotFoundError``를, airkorea는 ``AirKoreaNoDataError``를 던지고, 두
        라이브러리 모두 **자기 내부 페이지네이션에서 그 예외를 종료로 잡는다.**
        이 훅이 없으면 마지막 페이지 다음 요청이 asset 실패가 된다.
    warn:
        완성된 경고 문구를 받는 싱크(보통 ``logger.warning``). 경고는 드물게만
        발생하므로 lazy 포매팅 대신 문구를 만들어 넘긴다. 생략하면 경고가 사라지므로
        운영 경로에서는 반드시 주입한다 — 이 경고가 provider 행 누락의 유일한
        신호다.

    Yields
    ------
    provider item 원본. 본 헬퍼는 item을 해석하지 않는다.

    Raises
    ------
    ProviderPaginationOverrun
        ``max_pages``를 넘겼을 때.
    ProviderPaginationStalled
        ``fingerprint``를 주는 호출자에서 upstream이 같은 페이지를 반복할 때.
    """
    state = _PageState(
        num_of_rows=num_of_rows,
        label=label,
        ceiling=max_pages,
        absolute_ceiling=absolute_max_pages,
    )
    while True:
        state.page_no += 1
        state.guard_ceiling()
        try:
            page = fetch_page(state.page_no)
        except end_of_pages:
            if first_page_end_of_pages_is_failure and state.page_no == 1:
                raise
            # provider가 "더 없음"을 예외로 알렸다. 정상 종료다.
            state.note_end_of_pages(warn)
            return
        yield from state.absorb(page, warn)
        if state.finished:
            return


async def aiter_paginated_items(
    fetch_page: Callable[[int], Awaitable[ProviderPage]],
    *,
    num_of_rows: int,
    label: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    absolute_max_pages: int = DEFAULT_ABSOLUTE_MAX_PAGES,
    end_of_pages: tuple[type[BaseException], ...] = (),
    first_page_end_of_pages_is_failure: bool = False,
    warn: Callable[[str], None] | None = None,
) -> AsyncIterator[Any]:
    """:func:`iter_paginated_items`의 async 짝. **종료 규칙은 같은 한 벌이다.**

    async 클라이언트를 쓰는 provider가 생기면서 필요해졌다(khoa가 6.x에서 sync
    진입점을 전부 없앴다). 규칙을 두 벌로 복제하면 갈라진다 — 그래서 판정은
    :func:`_terminate` 하나가 소유하고, 여기서는 await 경계만 다르다.

    인자·예외·경고 계약은 sync 판과 동일하다. 그 문서는 위쪽을 보라.
    """
    state = _PageState(
        num_of_rows=num_of_rows,
        label=label,
        ceiling=max_pages,
        absolute_ceiling=absolute_max_pages,
    )
    while True:
        state.page_no += 1
        state.guard_ceiling()
        try:
            page = await fetch_page(state.page_no)
        except end_of_pages:
            if first_page_end_of_pages_is_failure and state.page_no == 1:
                raise
            state.note_end_of_pages(warn)
            return
        for item in state.absorb(page, warn):
            yield item
        if state.finished:
            return


@dataclass
class _PageState:
    """페이지네이션 종료 판정 상태 — sync/async 두 루프가 공유한다.

    이 클래스가 생긴 이유는 코드 재사용이 아니라 **규칙이 하나여야 하기**
    때문이다. 종료 조건(‘``total_count``가 권위, 짧은 페이지는 대체 휴리스틱’)을
    두 자리에 적으면 한쪽만 고쳐지는 날이 온다. 이 파일의 존재 이유가 바로 그
    부류의 사고다.
    """

    num_of_rows: int
    label: str
    ceiling: int
    absolute_ceiling: int = DEFAULT_ABSOLUTE_MAX_PAGES
    seen: int = 0
    declared: int | None = None
    page_no: int = 0
    finished: bool = False
    previous_fingerprint: Any = None
    declared_raised_ceiling: bool = False

    def guard_ceiling(self) -> None:
        effective = min(self.ceiling, self.absolute_ceiling)
        if self.page_no > effective:
            # 선언 건수가 **실제로** 상한을 올렸을 때만 그렇게 말한다. `max_pages`
            # 기본값이 절대 상한보다 큰 것은 선언과 무관하다(적대 리뷰 지적).
            blocked_by_absolute = (
                self.declared_raised_ceiling and self.absolute_ceiling < self.ceiling
            )
            raise ProviderPaginationOverrun(
                f"{self.label}: page 상한 {effective}를 넘겼다 "
                f"(수신 {self.seen}건, 선언 {self.declared}"
                + (
                    f", 선언 건수가 요구한 상한 {self.ceiling}는 절대 상한 "
                    f"{self.absolute_ceiling}에 막혔다"
                    if blocked_by_absolute
                    else ""
                )
                + "). "
                "upstream이 범위 밖 page에 빈 페이지를 주지 않거나 행을 과도하게 "
                "걸러내는지 확인할 것."
            )

    def note_end_of_pages(self, warn: Callable[[str], None] | None) -> None:
        if self.page_no == 1:
            # 첫 페이지에서 "더 없음"이면 이 순회는 **한 행도 받지 못했다**.
            # `declared`가 아직 None이라 아래 조건에 걸리지 않으므로 여기서 따로
            # 말한다 — 조용한 0행이 성공으로 보이는 것이 이 파일의 주제다.
            _emit(
                warn,
                f"{self.label}: 첫 페이지에서 end-of-pages — 한 행도 받지 못했다. "
                "빈 결과가 정상인 경계인지 확인해라(authoritative snapshot이면 "
                "`first_page_end_of_pages_is_failure=True`가 필요하다).",
            )
        if self.declared is not None and self.seen < self.declared:
            _emit(
                warn,
                f"{self.label}: upstream이 선언한 {self.declared}건 중 {self.seen}건에서 "
                f"페이지 종료를 알렸다 — provider 파싱 실패 행 가능성",
            )
        self.finished = True

    def absorb(
        self, page: ProviderPage, warn: Callable[[str], None] | None
    ) -> Sequence[Any]:
        """한 페이지를 흡수하고 yield할 item을 돌려준다. 종료는 ``finished``로 알린다."""
        items = list(page.items)
        if page.fingerprint is not None:
            if (
                self.previous_fingerprint is not None
                and page.fingerprint == self.previous_fingerprint
            ):
                raise ProviderPaginationStalled(
                    f"{self.label}: page {self.page_no}가 직전 페이지와 같은 내용을 "
                    f"돌려줬다 — upstream이 page_no를 전진시키지 않는다 "
                    f"(수신 {self.seen}건, 선언 {self.declared})."
                )
            self.previous_fingerprint = page.fingerprint
        if page.declared_total is not None:
            self.declared = page.declared_total
            # 선언 건수가 상한을 정한다. 전역 상한은 그보다 작을 때만 의미가 있다.
            needed = (
                -(-self.declared // self.num_of_rows) if self.num_of_rows > 0 else 1
            )
            raised = needed * _DECLARED_PAGE_SLACK + 1
            if raised > self.ceiling:
                self.ceiling = raised
                self.declared_raised_ceiling = True

        if not items:
            if self.declared is not None and self.seen < self.declared:
                _emit(
                    warn,
                    f"{self.label}: upstream이 선언한 {self.declared}건 중 "
                    f"{self.seen}건만 전달하고 페이지가 비었다 — "
                    "provider 파싱 실패 행 가능성",
                )
            self.finished = True
            return ()

        self.seen += len(items)
        if self.declared is not None:
            if (
                self.page_no == 1
                and self.seen == self.declared
                and len(items) == self.num_of_rows
            ):
                # **첫 페이지가 만재인데 선언 건수가 정확히 그만큼이다.**
                # provider가 응답에서 ``totalCount``를 못 받아 ``len(items)``로
                # 채운 모양일 수 있다(krforest ``_http.py``가 그렇게 한다). 그때
                # 선언을 권위로 믿으면 여기서 멈추고 **행 누락이 성공으로 보인다** —
                # 2026-09-13 실측: 2,500행 dataset에서 1,000행만 받고 끝났다.
                #
                # 종료 규칙은 바꾸지 않는다(바꾸면 범위 밖 page에 예외를 던지는
                # provider에서 새 실패를 만든다). 대신 **들리게** 한다.
                #
                # **이 경고의 한계 둘**을 적어 둔다. (1) 첫 페이지가 만재일 때만
                # 본다 — 부분 페이지에서 선언이 조작된 경우는 여전히 조용하다.
                # (2) 행 수가 정확히 페이지 크기의 배수인 정상 dataset에서도
                # 한 번 뜬다(오탐). 둘 다 "조용한 것보다 낫다"는 교환이다.
                _emit(
                    warn,
                    f"{self.label}: 첫 페이지가 {len(items)}/{self.num_of_rows}행 "
                    f"만재인데 선언 건수도 {self.declared}다 — provider가 "
                    "totalCount를 len(items)로 채웠을 수 있다. 실제 행이 더 있으면 "
                    "여기서 조용히 잘린다(확인 필요).",
                )
            if self.seen >= self.declared:
                self.finished = True
            elif len(items) < self.num_of_rows:
                # 이번 보정의 본체 — 짧은 페이지를 마지막 페이지로 읽지 않는다.
                _emit(
                    warn,
                    f"{self.label}: page {self.page_no}가 "
                    f"{len(items)}/{self.num_of_rows}행만 반환했으나 "
                    f"선언 {self.declared}건 중 {self.seen}건만 받았다 — "
                    "provider가 행을 걸렀을 수 있어 계속 페이지네이션한다",
                )
        elif len(items) < self.num_of_rows:
            # total_count가 없으면 짧은 페이지 외에 판정 근거가 없다.
            self.finished = True
        return items


def _emit(warn: Callable[[str], None] | None, message: str) -> None:
    """경고 싱크가 주입됐을 때만 문구를 넘긴다."""
    if warn is not None:
        warn(message)
