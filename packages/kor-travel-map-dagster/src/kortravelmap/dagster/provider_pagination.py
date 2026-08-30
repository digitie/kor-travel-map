"""provider 페이지네이션 종료 조건 (조용한 절단 방지).

## 왜 필요한가

data.go.kr 계열 provider 페이지네이션은 본 저장소 7곳에서 같은 관용구를 썼다::

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
``page_no > max_pages``       예외                  예외
===========================  ===================  ==========================

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

DEFAULT_MAX_PAGES: Final = 10_000
"""페이지 상한 — 무한 루프 방지용 안전장치이지 정상 종료 조건이 아니다.

page_no가 범위를 넘으면 upstream이 빈 페이지를 주는 것이 정상이다. 그러지 않고
마지막 페이지를 반복해 주는 upstream에서 루프가 갇히지 않게 한다. 1000 rows/page
기준 1000만 건이라 실 데이터셋에서 걸릴 값이 아니다.
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
        안전 상한. 넘기면 :class:`ProviderPaginationOverrun`.
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

    for page_no in range(1, max_pages + 1):
        page = fetch_page(page_no)
        items = list(page.items)
        if page.declared_total is not None:
            declared = page.declared_total

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

    raise ProviderPaginationOverrun(
        f"{label}: page 상한 {max_pages}를 넘겼다 (수신 {seen}건, "
        f"선언 {declared}). upstream이 범위 밖 page에 빈 페이지를 주지 않는지 확인할 것."
    )


def _emit(warn: Callable[[str], None] | None, message: str) -> None:
    """경고 싱크가 주입됐을 때만 문구를 넘긴다."""
    if warn is not None:
        warn(message)
