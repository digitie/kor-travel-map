"""절대 page 상한이 **실측 건수보다 충분히 위**인지 센다.

2026-09-19 prod: `feature_notice_krforest_landslide_forecast_issues_job`이
`ProviderPaginationOverrun: page 상한 10를 넘겼다 (수신 10000건, 선언 10562)`로
매번 실패했다. 상한 자체는 옳게 동작했다 — 조용한 절단 대신 시끄럽게 실패했다.
문제는 그 숫자의 근거가 **한 번 센 값을 적은 주석**("이 네 dataset은 모두 수천
행대")이었고, dataset이 자라면서 그 전제가 조용히 거짓이 됐다는 것이다.

그래서 근거를 상수로 꺼내고 여기서 여유를 센다. 다음에 어떤 dataset이 이 여유를
먹으면 **prod가 아니라 CI에서** 먼저 말한다.
"""

from __future__ import annotations

import math

from kortravelmap.dagster.provider_fetchers import (
    _KRFOREST_LARGEST_DECLARED_ROWS,
    _KRFOREST_MAX_PAGES,
)

#: 이 저장소의 krforest 호출이 쓰는 페이지 크기(`_iter_krforest_records`의 기본값).
_KRFOREST_NUM_OF_ROWS = 1000

#: 실측 최대치 대비 요구하는 최소 배수.
#:
#: 2배로 잡는다 — 산사태 예보발령은 발령마다 행이 쌓이는 append-only 피드라 계속
#: 자란다. 1.2배 같은 값은 몇 달 뒤 같은 사고를 낸다.
_REQUIRED_HEADROOM = 2


def test_krforest_page_ceiling_has_headroom_over_the_largest_observed_dataset() -> None:
    needed_pages = math.ceil(_KRFOREST_LARGEST_DECLARED_ROWS / _KRFOREST_NUM_OF_ROWS)
    assert needed_pages * _REQUIRED_HEADROOM <= _KRFOREST_MAX_PAGES, (
        f"절대 상한 {_KRFOREST_MAX_PAGES}장이 실측 최대 "
        f"{_KRFOREST_LARGEST_DECLARED_ROWS:,}행({needed_pages}장)의 "
        f"{_REQUIRED_HEADROOM}배에 못 미친다. 상한을 올리거나, dataset이 그만큼 자랐다면 "
        f"증분 수집으로 바꿀 때다."
    )


def test_the_observed_maximum_is_above_the_count_that_broke_prod() -> None:
    """실측 상수가 사고 당시 값 아래로 내려가지 않게 못박는다.

    이 상수를 낮추면 위 검사가 통과해 버려 상한을 다시 10장으로 되돌릴 수 있다 —
    그러면 사고가 그대로 돌아온다.
    """

    assert _KRFOREST_LARGEST_DECLARED_ROWS >= 10_562


def test_the_ceiling_still_refuses_an_absurd_declaration() -> None:
    """상한은 여전히 **천장**이어야 한다 — 거짓 선언에 끌려가면 안 된다.

    `absolute_max_pages`로 넘기는 이유가 그것이다(`max_pages`는 바닥이라 upstream이
    선언한 건수가 그 위로 올려 버린다). 여유를 준다고 그 성질까지 잃으면 안 되므로
    상한이 유한하고 상식적인 범위인지 센다.
    """

    assert _KRFOREST_MAX_PAGES < 1_000
