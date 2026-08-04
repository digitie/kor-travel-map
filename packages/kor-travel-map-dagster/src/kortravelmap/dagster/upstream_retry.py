"""upstream provider 단건 호출의 유한 재시도 (T-VN-H45).

data.go.kr 계열 upstream은 간헐 지연·5xx·게이트웨이 timeout이 일상이라, N건을
순차 호출하는 asset이 "예외 즉시 step 실패 → step 전량 재시도"만 가지면 시도당
생존 확률이 p^N으로 붕괴한다(H45 실측: KMA 격자 187+건 run이 단건 프로브 정상
상태에서도 매 주기 실패 — prod run 스택은 ``raise_for_kma_network_error``
= ``retryable=True`` network 분류였다).

**재시도 레이어 정산(적대 리뷰 1·2 H 반영)**: provider lib은 이미 transport
재시도를 소유한다(kma ``get_with_retries``·airkorea ``HttpClient`` — 기본
retries=3 → 4 HTTP 시도). 본 모듈은 그 위의 **두 번째** 레이어이므로 곱셈을
통제한다:

- 기본 attempts는 **2**(추가 1회) — 호출 지점은 client에 ``retries=1``을 함께
  주입해 총 HTTP 시도 상한을 경계당 2×2=4로 유지한다(레이어 도입 전 lib 단독
  4와 동일). timeout 20s 기준 경계당 최악 wall ≈ 2×(2×20+jitter)+backoff
  ≈ 84s, 187격자 병적 상한 ≈ 4.4h < dagster run 한도 6h.
- **쿼터/레이트리밋은 재시도하지 않는다**: 일일 쿼터 소진(kma resultCode 22 —
  ``failure_kind="quota"``/``"rate_limit"``)은 transient가 아니고, 재시도는
  쿼터 구멍만 키운다(``kma_weather_max_grids_per_run``의 일일 한도 보호 취지).
  lib이 ``retryable=True``로 분류해도 여기서 걸러낸다.
- **run 예산**(:class:`RetryBudget`): 상관 장애(전 격자 동시 열화)에서는 건별
  재시도가 무력하므로, run당 재시도 총량을 소진하면 이후 retryable 실패도
  즉시 전파해 run을 빨리 실패시킨다(early abort).
- 분류: kma 계열은 예외의 ``retryable`` 속성, 타 provider는 호출측
  ``is_retryable``로 타입 명시. 미분류(파싱·인증·계약 위반)는 즉시 전파 —
  fail-close 유지.
- 부분 실행 금지 불변식은 그대로다: attempts 소진 시 **원 예외를 원형
  그대로** 재던져 기존 실패 분류 경로를 탄다.
- backoff는 지수(2^n)·상한 capped·결정적(sleep은 호출 시점 late-binding —
  ``time.sleep``/``asyncio.sleep`` module-global 조회라 테스트에서 module
  단위 대체 가능). 동기 :func:`retry_upstream`의 backoff는 이벤트 루프
  위에서 소비되는 sync generator 안이라면 루프를 블록한다 — 예산·attempts
  2가 그 상한을 묶는다(비동기 경계는 :func:`retry_upstream_async`).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final, TypeVar

__all__ = [
    "DEFAULT_UPSTREAM_ATTEMPTS",
    "DEFAULT_UPSTREAM_BASE_DELAY_SECONDS",
    "DEFAULT_UPSTREAM_MAX_DELAY_SECONDS",
    "DEFAULT_UPSTREAM_RUN_RETRY_BUDGET",
    "NONRETRYABLE_FAILURE_KINDS",
    "PROVIDER_CLIENT_INNER_RETRIES",
    "RetryBudget",
    "default_upstream_retryable",
    "retry_upstream",
    "retry_upstream_async",
]

T = TypeVar("T")

DEFAULT_UPSTREAM_ATTEMPTS: Final[int] = 2
DEFAULT_UPSTREAM_BASE_DELAY_SECONDS: Final[float] = 2.0
DEFAULT_UPSTREAM_MAX_DELAY_SECONDS: Final[float] = 20.0
DEFAULT_UPSTREAM_RUN_RETRY_BUDGET: Final[int] = 8
PROVIDER_CLIENT_INNER_RETRIES: Final[int] = 1
"""client 주입용 내부 재시도 — 외부 attempts 2와 곱해 경계당 HTTP 4 시도 유지."""

PROVIDER_BOUNDARY_BASE_DELAY_SECONDS: Final[float] = 15.0
"""provider 호출 경계용 backoff(재리뷰 2 N-2) — lib 내부 재시도가 ~2s 안에
소진되므로, 외부 재시도가 "같은 4회를 0.2s 넓게"가 아니라 **수 초~수 분
장애에 대한 독립 시행**이 되도록 간격을 벌린다. 비용은 예산이 묶는다
(8 × 15s = 120s/run 상한)."""

NONRETRYABLE_FAILURE_KINDS: Final[frozenset[str]] = frozenset({"quota", "rate_limit"})
"""``retryable=True``여도 재시도하지 않는 failure_kind — 일일 쿼터 보호."""


def default_upstream_retryable(exc: BaseException) -> bool:
    """kma 계열 규약 — ``retryable=True``이면서 쿼터성 분류가 아닐 때만 재시도.

    ``retryable=False``(인증·파라미터 오류)와 속성 부재(미분류 — 파싱 등)는
    즉시 전파 대상이다.
    """

    if getattr(exc, "retryable", None) is not True:
        return False
    failure_kind = getattr(exc, "failure_kind", None)
    return failure_kind not in NONRETRYABLE_FAILURE_KINDS


@dataclass
class RetryBudget:
    """run 단위 재시도 총량 — 소진 후에는 retryable 실패도 즉시 전파(early abort).

    상관 장애(모든 호출이 동시에 열화)에서 N×backoff 전액을 지불하지 않기 위한
    상한이다. 하나의 asset run / fetch generator당 하나를 만들어 전 경계에
    공유한다.
    """

    limit: int = DEFAULT_UPSTREAM_RUN_RETRY_BUDGET
    used: int = field(default=0, init=False)

    def try_consume(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


def _backoff_delay(attempt: int, *, base_delay: float, max_delay: float) -> float:
    return min(max_delay, base_delay * (2.0 ** (attempt - 1)))


def _should_retry(
    exc: Exception,
    *,
    attempt: int,
    attempts: int,
    is_retryable: Callable[[BaseException], bool],
    budget: RetryBudget | None,
    label: str,
    on_retry: Callable[[str], None] | None,
) -> bool:
    """재시도 여부 판정 + 텔레메트리. 분류 통과 후에만 예산을 소모한다."""

    if attempt >= attempts or not is_retryable(exc):
        return False
    if budget is not None and not budget.try_consume():
        _notify(
            on_retry,
            f"upstream retry budget exhausted ({budget.limit}) — "
            f"{label}: {type(exc).__name__} 즉시 전파",
        )
        return False
    _notify(
        on_retry,
        f"upstream retry {label}: attempt {attempt}/{attempts} 실패 "
        f"({type(exc).__name__}: {exc}) — 재시도",
    )
    return True


def _notify(on_retry: Callable[[str], None] | None, message: str) -> None:
    """텔레메트리는 fallible — logger 실패가 upstream 원 예외를 덮으면 실패
    분류가 오진된다(리뷰 1 N-3). 삼키고 진행한다."""

    if on_retry is None:
        return
    # 진단 부수 경로 — logger 실패가 원 예외를 덮으면 실패 분류가 오진된다.
    with contextlib.suppress(Exception):
        on_retry(message)


def retry_upstream(
    call: Callable[[], T],
    *,
    label: str,
    is_retryable: Callable[[BaseException], bool] = default_upstream_retryable,
    attempts: int = DEFAULT_UPSTREAM_ATTEMPTS,
    base_delay: float = DEFAULT_UPSTREAM_BASE_DELAY_SECONDS,
    max_delay: float = DEFAULT_UPSTREAM_MAX_DELAY_SECONDS,
    budget: RetryBudget | None = None,
    on_retry: Callable[[str], None] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> T:
    """동기 upstream 단건 호출을 유한 재시도한다. ``label``은 진단용.

    ``sleep`` 기본은 호출 시점의 ``time.sleep``(late-binding — 테스트에서
    monkeypatch 가능).
    """

    if attempts < 1:
        raise ValueError(f"attempts must be >= 1: {attempts} ({label})")
    do_sleep = time.sleep if sleep is None else sleep
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            if not _should_retry(
                exc,
                attempt=attempt,
                attempts=attempts,
                is_retryable=is_retryable,
                budget=budget,
                label=label,
                on_retry=on_retry,
            ):
                raise
            do_sleep(
                _backoff_delay(attempt, base_delay=base_delay, max_delay=max_delay)
            )
    raise AssertionError(f"unreachable: {label}")  # pragma: no cover


async def retry_upstream_async(
    call: Callable[[], T],
    *,
    label: str,
    is_retryable: Callable[[BaseException], bool] = default_upstream_retryable,
    attempts: int = DEFAULT_UPSTREAM_ATTEMPTS,
    base_delay: float = DEFAULT_UPSTREAM_BASE_DELAY_SECONDS,
    max_delay: float = DEFAULT_UPSTREAM_MAX_DELAY_SECONDS,
    budget: RetryBudget | None = None,
    on_retry: Callable[[str], None] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> T:
    """async 문맥용 — 호출 자체는 호출측 규약대로(동기 client도 그대로) 실행하고
    backoff 대기만 event loop에 양보한다. cancellation(``BaseException``)은
    재시도로 삼키지 않는다. ``sleep`` 기본은 호출 시점의 ``asyncio.sleep``."""

    if attempts < 1:
        raise ValueError(f"attempts must be >= 1: {attempts} ({label})")
    do_sleep = asyncio.sleep if sleep is None else sleep
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            if not _should_retry(
                exc,
                attempt=attempt,
                attempts=attempts,
                is_retryable=is_retryable,
                budget=budget,
                label=label,
                on_retry=on_retry,
            ):
                raise
            await do_sleep(
                _backoff_delay(attempt, base_delay=base_delay, max_delay=max_delay)
            )
    raise AssertionError(f"unreachable: {label}")  # pragma: no cover
