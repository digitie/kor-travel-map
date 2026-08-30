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

from collections.abc import Callable, Iterator, Sequence
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
"""

_DECLARED_PAGE_SLACK: Final = 2
"""``total_count``를 알 때 허용하는 여유 배수.

provider가 행을 걸러 낼 수 있으므로 ``ceil(declared / num_of_rows)``보다 많은 페이지가
정상적으로 필요할 수 있다. 그러나 무한정은 아니다 — 절반이 걸러지는 상황이면 상한에
걸려 시끄럽게 실패하는 편이 낫다.
"""


class ProviderPaginationOverrun(RuntimeError):
    """페이지 상한을 넘겼다 — 조용히 자르지 않고 실패시킨다."""


@dataclass(frozen=True, slots=True)
class ProviderPage:
    """provider 1페이지의 종료 판정에 필요한 최소 정보.

    ``total_count``는 upstream이 선언한 전체 건수다. 알 수 없으면 ``None``이고,
    그때만 짧은 페이지 휴리스틱으로 되돌아간다.
    """

    items: Sequence[Any]
    total_count: int | None = None

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
    end_of_pages: tuple[type[BaseException], ...] = (),
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
        **큰 쪽**을 쓴다 — 선언 건수가 상한을 정하게 한다.
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
    """
    seen = 0
    declared: int | None = None
    ceiling = max_pages

    page_no = 0
    while True:
        page_no += 1
        if page_no > ceiling:
            raise ProviderPaginationOverrun(
                f"{label}: page 상한 {ceiling}를 넘겼다 (수신 {seen}건, 선언 {declared}). "
                "upstream이 범위 밖 page에 빈 페이지를 주지 않거나 행을 과도하게 "
                "걸러내는지 확인할 것."
            )
        try:
            page = fetch_page(page_no)
        except end_of_pages:
            # provider가 "더 없음"을 예외로 알렸다. 정상 종료다.
            if declared is not None and seen < declared:
                _emit(
                    warn,
                    f"{label}: upstream이 선언한 {declared}건 중 {seen}건에서 "
                    f"페이지 종료를 알렸다 — provider 파싱 실패 행 가능성",
                )
            return
        items = list(page.items)
        if page.declared_total is not None:
            declared = page.declared_total
            # 선언 건수가 상한을 정한다. 전역 상한은 그보다 작을 때만 의미가 있다.
            needed = -(-declared // num_of_rows) if num_of_rows > 0 else 1
            ceiling = max(ceiling, needed * _DECLARED_PAGE_SLACK + 1)

        if not items:
            if declared is not None and seen < declared:
                # upstream이 선언한 건수보다 적게 줬다. 절단 자체는 upstream/parse
                # 쪽이지만 조용히 넘어가면 적재 누락이 보이지 않는다.
                _emit(
                    warn,
                    f"{label}: upstream이 선언한 {declared}건 중 {seen}건만 전달하고 "
                    f"페이지가 비었다 — provider 파싱 실패 행 가능성",
                )
            return

        yield from items
        seen += len(items)

        if declared is not None:
            if seen >= declared:
                return
            if len(items) < num_of_rows:
                # 이번 보정의 본체 — 짧은 페이지를 마지막 페이지로 읽지 않는다.
                _emit(
                    warn,
                    f"{label}: page {page_no}가 {len(items)}/{num_of_rows}행만 반환했으나 "
                    f"선언 {declared}건 중 {seen}건만 받았다 — provider가 행을 걸렀을 수 "
                    f"있어 계속 페이지네이션한다",
                )
            continue

        if len(items) < num_of_rows:
            # total_count가 없으면 짧은 페이지 외에 판정 근거가 없다.
            return


def _emit(warn: Callable[[str], None] | None, message: str) -> None:
    """경고 싱크가 주입됐을 때만 문구를 넘긴다."""
    if warn is not None:
        warn(message)
