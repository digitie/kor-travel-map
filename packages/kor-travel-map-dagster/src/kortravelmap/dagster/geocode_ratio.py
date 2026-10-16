"""역지오코딩 빈 답 비율 판정 — MOIS와 공통 적재 루프가 공유하는 **한 곳**(ADR-108·109).

규칙이 둘이 아니라 행동이 둘이다: MOIS 재개형 적재는 문턱을 넘으면 run을 **degraded**(실패 아님)로
끝내고, 비-MOIS 공통 적재 루프는 run을 **실패**로 끝낸다(그 run의 스탬프는 commit 전이라 남지
않는다). 판정 — 표본 하한과 비율 — 은 여기 하나다.
"""

from __future__ import annotations

from typing import Final

__all__ = ["GEOCODE_RATIO_MIN_SAMPLE", "geocode_ratio_exceeded"]

#: 이보다 적게 조회했으면 비율을 판정하지 않는다 — 몇 건의 빈 답이 비율을 흔든다.
GEOCODE_RATIO_MIN_SAMPLE: Final[int] = 50


def geocode_ratio_exceeded(*, empty: int, total: int, ratio: float) -> bool:
    """``total``번 조회해 ``empty``번 빈 답이었을 때 문턱(``ratio``)을 넘었는가."""
    return total >= GEOCODE_RATIO_MIN_SAMPLE and empty > total * ratio
