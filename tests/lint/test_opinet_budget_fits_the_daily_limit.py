"""OpiNet 예산이 **실제 일일 한도** 아래에 있게 한다.

2026-09-14에 포털을 보고 알았다: 오피넷 무료키(일반 API 19종)의 일일 한도는
**300call/일**이고, 1,500call/일은 **유료 프리미엄 3종**의 값이다. 이 저장소는 그것을
1,500으로 알고 있었고 그 위에 예산 전체를 세웠다:

- ``opinet_run_call_budget`` 기본 600 → **한 run이 하루 한도의 2배**
- 같은 필드 상한 ``le=700`` → 하루 전체보다 큰 값을 설정할 수 있었다
- ``opinet_low_top_max_calls`` 기본 180 → ``get_area_codes``(~19)와 합쳐 한 run이
  하루의 66%

prod는 ``opinet_scope_mode=disabled``라 실제로 쓰이지는 않았다. 즉 **켜는 순간
드러났을 잠복 결함**이었고, 그것을 찾은 것은 계측이 아니라 **공식 자료를 한 번 본
것**이다. 이 task의 절반이 코드가 아니라 숫자였다는 말이 여기서도 맞았다.

그래서 여기서는 숫자 자체가 아니라 **산수가 성립하는지**를 결박한다 — 기본값을
올리는 사람은 이 파일을 함께 고쳐야 하고, 그 편집이 리뷰에 보인다.
"""

from __future__ import annotations

import pytest

from kortravelmap.settings import KorTravelMapSettings

pytestmark = pytest.mark.unit

#: 오피넷 무료키(일반 API 19종) 일일 한도. 출처: 오피넷 이용안내 > 유가정보 API
#: (2026-09-14 확인). 유료 프리미엄 3종은 1,500이고 Map은 그것을 쓰지 않는다 —
#: Map이 부르는 lowTop10 / 반경 내 주유소 검색 / 주유소 상세 / 지역코드는 전부
#: 일반 API 목록에 있다.
OPINET_FREE_DAILY_LIMIT: int = 300

#: 같은 날 OpiNet 경로를 도는 run 수의 최악값 — 일 1회 price + 월 1회 place가
#: 겹치는 날. `schedules.py`의 coalescing 주석이 같은 가정을 쓴다.
WORST_CASE_RUNS_PER_DAY: int = 2


def _settings() -> KorTravelMapSettings:
    return KorTravelMapSettings()


def test_two_runs_in_one_day_stay_under_the_free_limit() -> None:
    """하루 최악 2 run이 한도를 넘지 않는다 — 저장소 자신이 쓰는 산수다."""

    budget = _settings().opinet_run_call_budget
    spend = budget * WORST_CASE_RUNS_PER_DAY
    assert spend <= OPINET_FREE_DAILY_LIMIT, (
        f"run 예산 {budget} × {WORST_CASE_RUNS_PER_DAY} = {spend}회로 무료키 일일 "
        f"한도 {OPINET_FREE_DAILY_LIMIT}회를 넘는다. 이 저장소가 한도를 1,500으로 "
        "잘못 알고 600을 잡았던 것과 같은 형태다 — 올리려면 한도 쪽 근거부터 적어라."
    )


def test_a_single_run_cannot_be_configured_above_a_whole_day() -> None:
    """설정 상한 자체가 하루보다 커서는 안 된다.

    기본값이 맞아도 `le`가 하루 전체보다 크면 **설정 한 줄로** 한도를 넘길 수 있다.
    종전 `le=700`이 그랬다 — 한도(300)의 2.3배를 허용했다.
    """

    field = KorTravelMapSettings.model_fields["opinet_run_call_budget"]
    ceiling = next(
        (getattr(meta, "le", None) for meta in field.metadata if getattr(meta, "le", None)),
        None,
    )
    assert ceiling is not None, "run 예산에 상한(le)이 없다 — 무한 설정이 가능하다"
    assert ceiling <= OPINET_FREE_DAILY_LIMIT, (
        f"설정 상한 {ceiling}이 일일 한도 {OPINET_FREE_DAILY_LIMIT}보다 크다 — "
        "한 run이 하루보다 많이 쓰게 설정할 수 있으면 안 된다."
    )


def test_the_low_top_ceiling_fits_inside_the_run_budget() -> None:
    """`lowTop10` 상한이 run 예산 안에 들어간다.

    둘이 어긋나면 둘 중 하나는 거짓말이다 — 종전에는 lowTop 상한(180)이 실제 한도
    (300)의 60%였는데 run 예산(600)은 그것을 전혀 제약하지 않았다.
    """

    settings = _settings()
    area_codes = 19  # `get_area_codes` 실측 대략치 — 시도 단위라 거의 고정이다.
    needed = settings.opinet_low_top_max_calls + area_codes
    assert needed <= settings.opinet_run_call_budget, (
        f"lowTop 상한 {settings.opinet_low_top_max_calls} + get_area_codes(~{area_codes}) "
        f"= {needed}회가 run 예산 {settings.opinet_run_call_budget}을 넘는다 — "
        "lowTop만으로 예산이 소진되어 grid fallback이 영영 돌지 않는다."
    )
